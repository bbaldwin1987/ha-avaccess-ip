"""Transport layer for AV Access IP devices.

Two transports live here:

* TelnetClient — async, on-demand Telnet session against a device's shell
  (port 24). All stateful control and reads go through this. Each command opens,
  runs, and closes, serialized by a per-device lock (the firmware dislikes
  concurrent sessions).

* async_send_group_switch — fire-and-forget UDP broadcast on port 5010 used to
  switch many decoders to one source at once (msg_b_reconnect).

The "protocol" is just line I/O against a shell prompt ("/#" or "/ #"), with a
little Telnet IAC negotiation to strip.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket

from .const import (
    COMMAND_TIMEOUT,
    CONNECT_TIMEOUT,
    GROUP_SWITCH_PORT,
    LOGIN_USER,
    TELNET_PORT,
)

_LOGGER = logging.getLogger(__name__)

_IAC = 255
_DONT, _DO, _WONT, _WILL = 254, 253, 252, 251
_SB, _SE = 250, 240

# Prompt appears as "/#" and "/ #" across the guide. Match either at line end.
_PROMPT_RE = re.compile(rb"/ ?# ?$")


class TransportError(Exception):
    """Raised when a transport-level operation fails."""


class AuthError(TransportError):
    """Raised when login does not reach the shell prompt."""


def strip_telnet_negotiation(data: bytes) -> bytes:
    """Remove inline Telnet IAC command sequences from a byte stream."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == _IAC and i + 1 < n:
            cmd = data[i + 1]
            if cmd in (_DO, _DONT, _WILL, _WONT) and i + 2 < n:
                i += 3
                continue
            if cmd == _SB:
                j = i + 2
                while j + 1 < n and not (data[j] == _IAC and data[j + 1] == _SE):
                    j += 1
                i = j + 2
                continue
            if cmd == _IAC:
                out.append(_IAC)
                i += 2
                continue
            i += 2
            continue
        out.append(b)
        i += 1
    return bytes(out)


def clean_response(raw: bytes, command: str) -> str:
    """Decode device output and trim the echoed command and prompt lines."""
    text = strip_telnet_negotiation(raw).decode(errors="replace")
    cleaned: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s == command:
            continue
        if _PROMPT_RE.search(s.encode()):
            stripped = _PROMPT_RE.sub(b"", s.encode()).decode().strip()
            if not stripped:
                continue
            cleaned.append(stripped)
            continue
        cleaned.append(s)
    return "\n".join(cleaned).strip()


class TelnetClient:
    """On-demand async Telnet client for a single device."""

    def __init__(self, host: str) -> None:
        self._host = host
        self._lock = asyncio.Lock()

    @property
    def host(self) -> str:
        return self._host

    async def _read_until(self, reader, token, timeout):
        """Read until a literal byte token appears (used for 'login:')."""
        buf = bytearray()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"timeout waiting for {token!r}; got "
                    f"{strip_telnet_negotiation(bytes(buf))!r}"
                )
            try:
                chunk = await asyncio.wait_for(reader.read(256), remaining)
            except asyncio.TimeoutError as err:
                raise asyncio.TimeoutError(
                    f"timeout waiting for {token!r}; got "
                    f"{strip_telnet_negotiation(bytes(buf))!r}"
                ) from err
            if not chunk:
                raise ConnectionError(
                    f"connection closed before {token!r}; got "
                    f"{strip_telnet_negotiation(bytes(buf))!r}"
                )
            buf.extend(chunk)
            if token in strip_telnet_negotiation(bytes(buf)):
                return bytes(buf)

    async def _read_until_prompt(self, reader, timeout):
        """Read until a shell prompt ("/#" or "/ #") is seen."""
        buf = bytearray()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"timeout waiting for prompt; got "
                    f"{strip_telnet_negotiation(bytes(buf))!r}"
                )
            try:
                chunk = await asyncio.wait_for(reader.read(256), remaining)
            except asyncio.TimeoutError as err:
                raise asyncio.TimeoutError(
                    f"timeout waiting for prompt; got "
                    f"{strip_telnet_negotiation(bytes(buf))!r}"
                ) from err
            if not chunk:
                raise ConnectionError(
                    f"connection closed before prompt; got "
                    f"{strip_telnet_negotiation(bytes(buf))!r}"
                )
            buf.extend(chunk)
            cleaned = strip_telnet_negotiation(bytes(buf))
            for line in cleaned.split(b"\n"):
                if _PROMPT_RE.search(line):
                    return bytes(buf)

    async def _login(self, reader, writer):
        """Reach the shell prompt, handling an optional 'login:' challenge."""
        try:
            await self._read_until(reader, b"login:", timeout=4.0)
            writer.write((LOGIN_USER + "\n").encode())
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError):
            pass
        try:
            await self._read_until_prompt(reader, timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError:
            writer.write(b"\n")
            await writer.drain()
            try:
                await self._read_until_prompt(reader, timeout=COMMAND_TIMEOUT)
            except (asyncio.TimeoutError, ConnectionError) as err:
                raise AuthError(
                    f"did not reach shell prompt on {self._host}"
                ) from err

    async def command(self, command):
        """Open a session, run one command, return its cleaned output."""
        return (await self.commands([command]))[0]

    async def commands(self, commands):
        """Run a sequence of commands in a single session, in order."""
        async with self._lock:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, TELNET_PORT),
                    timeout=CONNECT_TIMEOUT,
                )
            except (OSError, asyncio.TimeoutError) as err:
                raise TransportError(
                    f"cannot connect to {self._host}:{TELNET_PORT}: {err}"
                ) from err
            try:
                await self._login(reader, writer)
                results = []
                for cmd in commands:
                    writer.write((cmd + "\n").encode())
                    await writer.drain()
                    raw = await self._read_until_prompt(
                        reader, timeout=COMMAND_TIMEOUT
                    )
                    results.append(clean_response(raw, cmd))
                return results
            except (asyncio.TimeoutError, ConnectionError) as err:
                raise TransportError(
                    f"command failed on {self._host}: {err}"
                ) from err
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def async_test_connection(self):
        """Return True if we can log in and read the prompt."""
        try:
            await self.command("")
            return True
        except TransportError:
            return False


async def async_send_group_switch(
    tx_name, rx_names, session_number, broadcast_addr="255.255.255.255"
):
    """Send a msg_b_reconnect UDP broadcast to switch many RXs at once.

    Format (guide section 8):
        msg_b_reconnect tx_name:session_number:rx_number rx1 rx2 ... rxN
    """
    payload = (
        f"msg_b_reconnect {tx_name}:{session_number}:{len(rx_names)} "
        + " ".join(rx_names)
    ).encode()

    loop = asyncio.get_running_loop()

    def _send():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(payload, (broadcast_addr, GROUP_SWITCH_PORT))
        finally:
            sock.close()

    await loop.run_in_executor(None, _send)
    _LOGGER.debug("Sent group switch: %s", payload)
