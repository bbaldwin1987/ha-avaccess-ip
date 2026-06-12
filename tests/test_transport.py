"""Tests for the Telnet transport against a mock device shell (no HA needed)."""

import asyncio
import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "custom_components"
    ),
)

from avaccess_ip import transport as t  # noqa: E402


# ---- pure helpers -----------------------------------------------------------

def test_strip_telnet_negotiation_removes_iac():
    # IAC DO ECHO (255 253 1) wrapping "hi"
    data = bytes([0xFF, 0xFD, 0x01]) + b"hi" + bytes([0xFF, 0xFB, 0x03])
    assert t.strip_telnet_negotiation(data) == b"hi"


def test_strip_telnet_negotiation_escaped_ff():
    data = bytes([0xFF, 0xFF]) + b"x"
    assert t.strip_telnet_negotiation(data) == bytes([0xFF]) + b"x"


def test_clean_response_trims_echo_and_prompt():
    raw = b"cat /etc/version\r\nIPE935\r\nV1.0.23t1\r\n/ # "
    out = t.clean_response(raw, "cat /etc/version")
    assert "IPE935" in out
    assert "V1.0.23t1" in out
    assert "cat /etc/version" not in out


# ---- mock device shell ------------------------------------------------------

class MockDevice:
    """A tiny TCP server emulating the device's login + shell prompt."""

    def __init__(self, responses, send_login=True, send_iac=True):
        self.responses = responses          # dict: command -> output text
        self.send_login = send_login
        self.send_iac = send_iac
        self.server = None
        self.port = None
        self.received = []

    async def start(self):
        self.server = await asyncio.start_server(
            self._handle, "127.0.0.1", 0
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader, writer):
        if self.send_iac:
            writer.write(bytes([0xFF, 0xFD, 0x01]))  # IAC DO ECHO
        if self.send_login:
            writer.write(b"IPE935-341B22822FEF login: ")
            await writer.drain()
            await reader.readline()  # consume the username
        writer.write(b"Welcome.\r\n/ # ")
        await writer.drain()
        while True:
            line = await reader.readline()
            if not line:
                break
            cmd = line.decode(errors="replace").strip()
            self.received.append(cmd)
            output = self.responses.get(cmd, "")
            if output:
                writer.write((output + "\r\n").encode())
            writer.write(b"/ # ")
            await writer.drain()


@pytest.mark.asyncio
async def test_command_reads_response():
    mock = MockDevice(
        {
            "cat /etc/version": "IPE935\nV1.0.23t1\nWed, 17 May 2023",
            "gbparam g alias": "ConfRoom",
        }
    )
    await mock.start()
    try:
        client = t.TelnetClient("127.0.0.1")
        # point the client at the mock port by monkeypatching the constant use
        import avaccess_ip.transport as tr

        orig = tr.TELNET_PORT
        tr.TELNET_PORT = mock.port
        try:
            version = await client.command("cat /etc/version")
            alias = await client.command("gbparam g alias")
        finally:
            tr.TELNET_PORT = orig
        assert "IPE935" in version
        assert "V1.0.23t1" in version
        assert alias == "ConfRoom"
        assert "cat /etc/version" in mock.received
    finally:
        await mock.stop()


@pytest.mark.asyncio
async def test_commands_run_in_order_same_session():
    mock = MockDevice(
        {
            "gbconfig --source-select=341B22822FEF": "",
            "e e_reconnect": "",
        }
    )
    await mock.start()
    try:
        client = t.TelnetClient("127.0.0.1")
        import avaccess_ip.transport as tr

        orig = tr.TELNET_PORT
        tr.TELNET_PORT = mock.port
        try:
            await client.commands(
                ["gbconfig --source-select=341B22822FEF", "e e_reconnect"]
            )
        finally:
            tr.TELNET_PORT = orig
        assert mock.received == [
            "gbconfig --source-select=341B22822FEF",
            "e e_reconnect",
        ]
    finally:
        await mock.stop()


@pytest.mark.asyncio
async def test_no_login_prompt_still_works():
    """Some firmware drops straight to a shell — no 'login:' line."""
    mock = MockDevice({"cat /etc/version": "IPD935\nV1.0.5"}, send_login=False)
    await mock.start()
    try:
        client = t.TelnetClient("127.0.0.1")
        import avaccess_ip.transport as tr

        orig = tr.TELNET_PORT
        tr.TELNET_PORT = mock.port
        try:
            out = await client.command("cat /etc/version")
        finally:
            tr.TELNET_PORT = orig
        assert "IPD935" in out
    finally:
        await mock.stop()


@pytest.mark.asyncio
async def test_connect_failure_raises():
    client = t.TelnetClient("127.0.0.1")
    import avaccess_ip.transport as tr

    orig_port = tr.TELNET_PORT
    orig_timeout = tr.CONNECT_TIMEOUT
    tr.TELNET_PORT = 1  # nothing listening
    tr.CONNECT_TIMEOUT = 0.5  # Windows can stall a long time on refused ports
    try:
        with pytest.raises(t.TransportError):
            await client.command("cat /etc/version")
    finally:
        tr.TELNET_PORT = orig_port
        tr.CONNECT_TIMEOUT = orig_timeout
