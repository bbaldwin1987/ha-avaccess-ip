#!/usr/bin/env python3
"""
Phase 0 hardware-validation spike for AV Access HDIP100 / 4KIP200 devices.

This is a THROWAWAY diagnostic script — it is NOT part of the Home Assistant
integration. Its only job is to answer the questions the API guide can't, by
poking a single real device over Telnet:

  * Does login drop straight to a shell, or present a password prompt?
  * What does the prompt look like byte-for-byte? (we assume "/#")
  * How long does connect/login take?
  * Does a read command (cat /etc/version) round-trip cleanly?
  * (optional) Does a real routing switch take effect and read back?

Dependency-free: standard library only. Run it from any machine that can reach
the device's IP on TCP port 24.

USAGE
    python spike.py <device_ip>
    python spike.py <device_ip> --verbose
    # optional, WRITES to the device — switches this RX to a TX, then reads back:
    python spike.py <rx_ip> --switch-to <TX_MAC>
    # optional, undo:
    python spike.py <rx_ip> --switch-to NULL

Examples
    python spike.py 192.168.1.50
    python spike.py 192.168.1.50 --switch-to 341B22822FEF
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

# --- protocol constants (from API Command Guide V1.0.3) -----------------------
TELNET_PORT = 24
LOGIN_USER = "root"
PROMPT = b"/#"            # success prompt per guide section 7.1.1
CONNECT_TIMEOUT = 10.0   # seconds
READ_TIMEOUT = 10.0      # seconds to wait for the prompt after a command

# Telnet IAC negotiation bytes — embedded devices often send a little of this
IAC = 255
DONT, DO, WONT, WILL = 254, 253, 252, 251
SB, SE = 250, 240


def _strip_telnet_negotiation(data: bytes) -> bytes:
    """Remove inline Telnet IAC command sequences so we see clean shell text.

    Replies WONT/DONT to every negotiation are handled at a higher level; here
    we just strip the bytes from the data stream for prompt matching.
    """
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == IAC and i + 1 < n:
            cmd = data[i + 1]
            if cmd in (DO, DONT, WILL, WONT) and i + 2 < n:
                i += 3
                continue
            if cmd == SB:  # subnegotiation: skip until IAC SE
                j = i + 2
                while j + 1 < n and not (data[j] == IAC and data[j + 1] == SE):
                    j += 1
                i = j + 2
                continue
            if cmd == IAC:  # escaped 0xFF literal
                out.append(IAC)
                i += 2
                continue
            i += 2
            continue
        out.append(b)
        i += 1
    return bytes(out)


async def _read_until(reader: asyncio.StreamReader, token: bytes,
                      timeout: float, verbose: bool = False) -> bytes:
    """Read from the stream until `token` appears (after stripping IAC)."""
    buf = bytearray()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError(
                f"timed out waiting for {token!r}; got so far: "
                f"{_strip_telnet_negotiation(bytes(buf))!r}"
            )
        try:
            chunk = await asyncio.wait_for(reader.read(256), timeout=remaining)
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f"timed out waiting for {token!r}; got so far: "
                f"{_strip_telnet_negotiation(bytes(buf))!r}"
            )
        if not chunk:  # connection closed
            raise ConnectionError(
                f"connection closed before {token!r}; got: "
                f"{_strip_telnet_negotiation(bytes(buf))!r}"
            )
        buf.extend(chunk)
        if verbose:
            print(f"    << {chunk!r}")
        if token in _strip_telnet_negotiation(bytes(buf)):
            return _strip_telnet_negotiation(bytes(buf))


async def run(ip: str, switch_to: str | None, verbose: bool) -> int:
    print(f"[*] Connecting to {ip}:{TELNET_PORT} ...")
    t0 = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, TELNET_PORT), timeout=CONNECT_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError) as err:
        print(f"[!] Could not connect: {err}")
        return 2
    print(f"[+] TCP connected in {time.monotonic() - t0:.2f}s")

    try:
        # Some devices print "login:" and expect a username; others drop to a
        # shell. We try to read whatever greets us, then send the username.
        try:
            greeting = await _read_until(reader, b"login:", timeout=4.0,
                                         verbose=verbose)
            print("[+] Saw a 'login:' prompt — sending username 'root'")
            print(f"    greeting bytes: {greeting!r}")
            writer.write((LOGIN_USER + "\n").encode())
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError):
            print("[i] No 'login:' prompt seen within 4s — device may drop "
                  "straight to a shell. Continuing to look for the prompt.")

        # Now wait for the shell prompt "/#"
        try:
            await _read_until(reader, PROMPT, timeout=READ_TIMEOUT,
                              verbose=verbose)
        except asyncio.TimeoutError:
            # try nudging with a newline once
            writer.write(b"\n")
            await writer.drain()
            await _read_until(reader, PROMPT, timeout=READ_TIMEOUT,
                              verbose=verbose)
        print(f"[+] Got shell prompt {PROMPT!r} — login OK "
              f"({time.monotonic() - t0:.2f}s total)")

        async def command(cmd: str) -> str:
            if verbose:
                print(f"    >> {cmd}")
            writer.write((cmd + "\n").encode())
            await writer.drain()
            raw = await _read_until(reader, PROMPT, timeout=READ_TIMEOUT,
                                    verbose=verbose)
            text = raw.decode(errors="replace")
            # Trim echoed command and trailing prompt for readability
            lines = [ln for ln in text.splitlines()
                     if ln.strip() and ln.strip() != cmd
                     and not ln.strip().endswith("/#")
                     and ln.strip() != "/ #"]
            return "\n".join(lines).strip()

        # --- READ checks ------------------------------------------------------
        print("\n[*] Reading firmware version (cat /etc/version):")
        print("    " + (await command("cat /etc/version")).replace("\n", "\n    "))

        print("\n[*] Reading alias (gbparam g alias):")
        print("    " + (await command("gbparam g alias") or "(empty)"))

        print("\n[*] Reading current video source (gbconfig --show --source-select):")
        print("    " + (await command("gbconfig --show --source-select") or "(none)"))

        # --- optional WRITE check --------------------------------------------
        if switch_to is not None:
            print(f"\n[!] WRITE TEST: switching this RX to source '{switch_to}'")
            await command(f"gbconfig --source-select={switch_to}")
            await command("e e_reconnect")
            print("[*] Re-reading source after switch:")
            await asyncio.sleep(1.0)
            print("    " + (await command("gbconfig --show --source-select")
                            or "(none)"))

        print("\n[✓] Spike complete — transport assumptions validated.")
        return 0

    except (asyncio.TimeoutError, ConnectionError) as err:
        print(f"\n[!] Protocol error: {err}")
        print("    => Login/prompt assumptions may need adjustment. Re-run "
              "with --verbose to see raw bytes.")
        return 3
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ip", help="device IP address")
    p.add_argument("--switch-to", metavar="TX_MAC", default=None,
                   help="WRITES: switch this RX to the given TX MAC (or NULL)")
    p.add_argument("--verbose", action="store_true",
                   help="print raw bytes read/written")
    args = p.parse_args()
    try:
        return asyncio.run(run(args.ip, args.switch_to, args.verbose))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
