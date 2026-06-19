"""Unit tests for the hardware-independent device logic (no HA required)."""

import os
import sys

import pytest

# Make the integration package importable as `avaccess_ip`.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "custom_components"
    ),
)

from avaccess_ip import device as d  # noqa: E402
from avaccess_ip.const import (  # noqa: E402
    TYPE_DECODER,
    TYPE_ENCODER,
    TYPE_MRX,
)


# ---- parse_hostname / classify ----------------------------------------------

@pytest.mark.parametrize(
    "hostname,prefix,mac",
    [
        ("IPE935-341B22822FEF", "IPE935", "341B22822FEF"),
        ("IPD935-341B228007BD", "IPD935", "341B228007BD"),
        ("IPM4000-5ECC51593001", "IPM4000", "5ECC51593001"),
        ("ipe915-aabbccddeeff", "IPE915", "AABBCCDDEEFF"),
        ("IPE35-361B22094013", "IPE35", "361B22094013"),  # guide typo, still parses
    ],
)
def test_parse_hostname_ok(hostname, prefix, mac):
    assert d.parse_hostname(hostname) == (prefix, mac)


@pytest.mark.parametrize("bad", ["", "noseparator", "IPE935-XYZ", "IPE935-12"])
def test_parse_hostname_bad(bad):
    assert d.parse_hostname(bad) == (None, None)


def test_classify_known():
    assert d.classify("IPE935") == (TYPE_ENCODER, "4KIP200E", True)
    assert d.classify("IPD935") == (TYPE_DECODER, "4KIP200D", True)
    assert d.classify("IPM4000") == (TYPE_MRX, "4KIP200M", True)
    assert d.classify("IPE915") == (TYPE_ENCODER, "HDIP100E", False)


def test_classify_unknown_defaults_to_decoder():
    dtype, model, is4k = d.classify("WHATISTHIS")
    assert dtype == TYPE_DECODER
    assert model == "WHATISTHIS"


# ---- normalize_mac ----------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("IPE935-341B22822FEF", "341B22822FEF"),
        ("341B22822FEF", "341B22822FEF"),
        ("34:1b:22:82:2f:ef", "341B22822FEF"),
        ("34-1b-22-82-2f-ef", "341B22822FEF"),
        ("NULL", "NULL"),
        ("null", "NULL"),
    ],
)
def test_normalize_mac(raw, expected):
    assert d.normalize_mac(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('"alias" not defined', None),
        ('"alias" not defined/ #', None),
        ("", None),
        (None, None),
        ("Kitchen TV", "Kitchen TV"),
        ('"Kitchen TV"', "Kitchen TV"),
    ],
)
def test_clean_alias(raw, expected):
    assert d.clean_alias(raw) == expected


# ---- command builders -------------------------------------------------------

def test_cmd_set_source_includes_commit():
    cmds = d.cmd_set_source("IPE935-341B22822FEF")
    assert cmds == [
        "gbconfig --source-select=341B22822FEF",
        "e e_reconnect",
    ]


def test_cmd_set_source_null():
    cmds = d.cmd_set_source("NULL")
    assert cmds[0] == "gbconfig --source-select=NULL"
    assert cmds[1] == "e e_reconnect"


def test_cmd_sinkpower():
    assert d.cmd_sinkpower(True) == "sinkpower on"
    assert d.cmd_sinkpower(False) == "sinkpower off"


def test_cmd_set_cec_codes():
    assert d.cmd_set_cec_codes("40 04", "ff 36") == [
        'gbparam s cec_poweron_cmd "40 04"',
        'gbparam s cec_standby_cmd "ff 36"',
    ]


def test_cmd_set_rs232_codes_hex_flag():
    cmds = d.cmd_set_rs232_codes("AA", "BB", hex_enable=True)
    assert cmds[0] == "gbconfig --rs232-hex-cmd-enable y"
    cmds = d.cmd_set_rs232_codes("AA", "BB", hex_enable=False)
    assert cmds[0] == "gbconfig --rs232-hex-cmd-enable n"


def test_cmd_get_source():
    assert d.cmd_get_source() == "gbconfig --show --source-select"


def test_cmd_get_hostname():
    assert d.cmd_get_hostname() == "hostname"


def test_cmd_send_cec():
    assert d.cmd_send_cec("40 04") == 'cec -s "40 04"'


def test_cmd_reboot():
    assert d.cmd_reboot() == "reboot"


# ---- AVDevice identity ------------------------------------------------------

def test_avdevice_unique_id_prefers_mac():
    dev = d.AVDevice(host="192.168.1.5", device_type=TYPE_DECODER)
    dev.mac = "341B22822FEF"
    assert dev.unique_id == "341b22822fef"


def test_avdevice_unique_id_falls_back_to_host():
    dev = d.AVDevice(host="192.168.1.5", device_type=TYPE_DECODER)
    assert dev.unique_id == "192.168.1.5"


def test_avdevice_name_precedence():
    dev = d.AVDevice(host="192.168.1.5", device_type=TYPE_DECODER)
    assert dev.device_info_name() == "192.168.1.5"
    dev.hostname = "IPD935-341B22822FEF"
    assert dev.device_info_name() == "IPD935-341B22822FEF"
    dev.alias = "Conference Room"
    assert dev.device_info_name() == "Conference Room"
    dev.alias = '"alias" not defined'
    assert dev.device_info_name() == "IPD935-341B22822FEF"


@pytest.mark.asyncio
async def test_async_identify_sets_hostname_mac_and_preserves_alias(monkeypatch):
    dev = d.AVDevice(host="192.168.1.5", device_type=TYPE_DECODER, alias="Kitchen TV")

    async def fake_command(command):
        responses = {
            "hostname": "IPD935-341B22822FEF",
            "cat /etc/version": "IPD935\nV1.0.5",
            "gbparam g alias": "",
            "gbconfig --show --source-select": "IPE935-AABBCCDDEEFF",
        }
        return responses[command]

    monkeypatch.setattr(dev.client, "command", fake_command)

    await dev.async_identify()

    assert dev.hostname == "IPD935-341B22822FEF"
    assert dev.mac == "341B22822FEF"
    assert dev.alias == "Kitchen TV"
    assert dev.current_source_mac == "AABBCCDDEEFF"
