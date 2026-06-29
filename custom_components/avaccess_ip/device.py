"""Device model and command builders for AV Access IP devices.

This module is deliberately free of Home Assistant imports so it can be unit
tested standalone. It encapsulates:

* :func:`parse_hostname` — split a device hostname into model prefix + MAC.
* :func:`classify` — map a model prefix to type / friendly model / capability.
* :class:`AVDevice` — a single device (TX/RX/MRX) wrapping a TelnetClient,
  with high-level async helpers that build the correct command strings and
  enforce the commit semantics (``e e_reconnect`` after routing).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .const import (
    DEFAULT_CEC_POWERON,
    DEFAULT_CEC_STANDBY,
    DEFAULT_RS232_PARAM,
    MANUFACTURER,
    MODEL_MAP,
    SOURCE_NULL,
    TYPE_DECODER,
    TYPE_ENCODER,
    TYPE_MRX,
)
from .transport import TelnetClient

_LOGGER = logging.getLogger(__name__)

SAMSUNG_FRAME_ART_ON = "08 22 0B 0B 0E 01 B1"
SAMSUNG_FRAME_ART_OFF = "08 22 0B 0B 0E 00 B2"

# Hostname looks like "IPE935-341B22822FEF": <prefix>-<12 hex MAC>.
# Be lenient: the guide itself contains a typo ("IPE35-..."), so we match a
# prefix of letters+digits, a hyphen, then 12 hex chars.
_HOSTNAME_RE = re.compile(r"^([A-Za-z0-9]+)-([0-9A-Fa-f]{12})$")
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")


def parse_hostname(hostname: str) -> tuple[str | None, str | None]:
    """Return (model_prefix, mac) from a hostname, or (None, None)."""
    m = _HOSTNAME_RE.match(hostname.strip())
    if not m:
        return None, None
    return m.group(1).upper(), m.group(2).upper()


def classify(model_prefix: str) -> tuple[str, str, bool]:
    """Map a model prefix to (device_type, friendly_model, is_4k).

    Falls back to a generic decoder classification for unknown prefixes so the
    integration degrades gracefully rather than refusing the device.
    """
    if model_prefix in MODEL_MAP:
        return MODEL_MAP[model_prefix]
    _LOGGER.warning("Unknown model prefix %s; treating as decoder", model_prefix)
    return (TYPE_DECODER, model_prefix, True)


def normalize_mac(value: str) -> str:
    """Strip any model prefix and punctuation, returning a bare 12-hex MAC.

    Accepts "IPE935-341B22822FEF", "341B22822FEF", "34:1b:22:82:2f:ef", etc.
    """
    value = value.strip()
    if value.upper() == SOURCE_NULL:
        return SOURCE_NULL
    if "-" in value:  # hostname form
        _, mac = parse_hostname(value)
        if mac:
            return mac
    hexonly = re.sub(r"[^0-9A-Fa-f]", "", value)
    if _MAC_RE.match(hexonly):
        return hexonly.upper()
    return value  # leave as-is; caller validates


def clean_alias(value: str | None) -> str | None:
    """Return a usable alias, ignoring firmware's not-defined sentinel."""
    if not value:
        return None
    alias = value.strip().strip('"')
    if not alias or "not defined" in alias.lower():
        return None
    return alias


# ---- command builders (pure functions, easy to unit test) --------------------

def cmd_get_version() -> str:
    return "cat /etc/version"


def cmd_get_hostname() -> str:
    return "hostname"


def cmd_get_alias() -> str:
    return "gbparam g alias"


def cmd_set_alias(alias: str) -> str:
    return f"gbparam s alias {alias}"


def cmd_get_source() -> str:
    """Read the bonded source (returns the TX MAC)."""
    return "gbconfig --show --source-select"


def cmd_set_source(mac: str) -> list[str]:
    """Route a bonded source to this RX, with the required commit command."""
    mac = normalize_mac(mac)
    return [f"gbconfig --source-select={mac}", "e e_reconnect"]


def cmd_sinkpower(on: bool) -> str:
    return "sinkpower on" if on else "sinkpower off"


def cmd_set_sinkpower_mode(mode: str) -> list[str]:
    return [
        f"gbconfig --sinkpower-mode={mode}",
        f"gbparam s sinkpower_mode {mode}",
    ]


def cmd_set_cec_codes(poweron: str, standby: str) -> list[str]:
    return [
        f'gbparam s cec_poweron_cmd "{poweron}"',
        f'gbparam s cec_standby_cmd "{standby}"',
    ]


def cmd_set_rs232_codes(
    poweron: str,
    standby: str,
    hex_enable: bool,
    rs232_param: str = DEFAULT_RS232_PARAM,
) -> list[str]:
    return [
        "gbconfig --rs232-enable=y",
        f"gbconfig --rs232-param={rs232_param}",
        "gbconfig --sinkpower-rs232=y",
        f"gbconfig --rs232-hex-cmd-enable={'y' if hex_enable else 'n'}",
        f'gbparam s rs232_poweron_cmd "{poweron}"',
        f'gbparam s rs232_standby_cmd "{standby}"',
    ]


def cmd_send_cec(cec_string: str) -> str:
    return f'cec -s "{cec_string}"'


def cmd_reboot() -> str:
    return "reboot"


def cmd_get_rs232_poweron() -> str:
    return "gbparam g rs232_poweron_cmd"


def cmd_get_rs232_standby() -> str:
    return "gbparam g rs232_standby_cmd"


@dataclass
class AVDevice:
    """A single AV Access device reachable at ``host``."""

    host: str
    device_type: str
    hostname: str | None = None         # full "IPE935-MAC" once known
    mac: str | None = None              # bare 12-hex
    model_prefix: str | None = None
    model: str | None = None
    is_4k: bool = True
    firmware: str | None = None
    alias: str | None = None
    available: bool = False
    current_source_mac: str | None = None   # for RX: bonded source MAC
    client: TelnetClient = field(init=False)

    def __post_init__(self) -> None:
        self.client = TelnetClient(self.host)

    # -- identity ------------------------------------------------------------
    @property
    def is_decoder(self) -> bool:
        return self.device_type in (TYPE_DECODER, TYPE_MRX)

    @property
    def is_encoder(self) -> bool:
        return self.device_type == TYPE_ENCODER

    @property
    def unique_id(self) -> str:
        """Stable id for HA — MAC if known, else host."""
        return (self.mac or self.host).lower()

    def device_info_name(self) -> str:
        return clean_alias(self.alias) or self.hostname or self.host

    # -- async operations ----------------------------------------------------
    async def async_identify(self) -> None:
        """Read version/alias/source and populate identity fields.

        Reads the firmware block (which begins with the model prefix), the
        alias, and — for decoders — the current source.
        """
        hostname = await self.client.command(cmd_get_hostname())
        prefix, mac = parse_hostname(hostname)
        if prefix and mac:
            self.hostname = hostname.strip()
            self.model_prefix = prefix
            self.mac = mac

        version_block = await self.client.command(cmd_get_version())
        # version block first line is the model prefix, e.g. "IPE935"
        first = version_block.splitlines()[0].strip() if version_block else ""
        if first:
            self.model_prefix = first.upper()
            self.device_type, self.model, self.is_4k = classify(self.model_prefix)
        # firmware = the version line (commonly second line, e.g. V1.0.23t1)
        lines = [l.strip() for l in version_block.splitlines() if l.strip()]
        if len(lines) >= 2:
            self.firmware = lines[1]

        alias = clean_alias(await self.client.command(cmd_get_alias()))
        self.alias = alias or clean_alias(self.alias)

        if self.is_decoder:
            await self.async_update_source()
        self.available = True

    async def async_update_source(self) -> str | None:
        """Refresh and return the current bonded source MAC (decoder only)."""
        raw = await self.client.command(cmd_get_source())
        mac = normalize_mac(raw) if raw else None
        if mac in (None, "", SOURCE_NULL):
            self.current_source_mac = None
        else:
            self.current_source_mac = mac
        return self.current_source_mac

    async def async_set_source(self, mac: str) -> None:
        """Route a bonded source (TX MAC) to this decoder and commit."""
        await self.client.commands(cmd_set_source(mac))
        normalized = normalize_mac(mac)
        self.current_source_mac = None if normalized == SOURCE_NULL else normalized

    async def async_clear_source(self) -> None:
        await self.async_set_source(SOURCE_NULL)

    async def async_send_cec(self, cec_string: str) -> None:
        await self.client.command(cmd_send_cec(cec_string))

    async def async_reboot(self) -> None:
        await self.client.command(cmd_reboot())

    async def async_send_samsung_frame_art_mode(self, enabled: bool) -> None:
        """Send Samsung Frame Art Mode over RS232, restoring power codes after.

        The decoder exposes RS232 transmission through ``sinkpower`` using the
        stored power-on/standby command slots. For discrete Art Mode control we
        temporarily load the Art command pair, trigger sinkpower, then restore
        the previously configured display power commands.
        """
        current_on, current_off = await self.client.commands(
            [cmd_get_rs232_poweron(), cmd_get_rs232_standby()]
        )
        restore_on = clean_alias(current_on) or current_on
        restore_off = clean_alias(current_off) or current_off
        try:
            await self.client.commands(
                cmd_set_sinkpower_mode("rs232")
                + cmd_set_rs232_codes(
                    SAMSUNG_FRAME_ART_ON,
                    SAMSUNG_FRAME_ART_OFF,
                    True,
                    DEFAULT_RS232_PARAM,
                )
                + [cmd_sinkpower(enabled)]
            )
        finally:
            if restore_on and restore_off:
                await self.client.commands(
                    cmd_set_rs232_codes(
                        restore_on,
                        restore_off,
                        True,
                        DEFAULT_RS232_PARAM,
                    )
                )

    async def async_set_display_power(self, on: bool) -> None:
        await self.client.command(cmd_sinkpower(on))

    async def async_configure_power(
        self,
        mode: str,
        cec_poweron: str = DEFAULT_CEC_POWERON,
        cec_standby: str = DEFAULT_CEC_STANDBY,
        rs232_poweron: str | None = None,
        rs232_standby: str | None = None,
        rs232_hex: bool = False,
        rs232_param: str = DEFAULT_RS232_PARAM,
    ) -> None:
        """Apply per-decoder display-power configuration."""
        cmds = cmd_set_sinkpower_mode(mode)
        if mode in ("cec", "both"):
            cmds += cmd_set_cec_codes(cec_poweron, cec_standby)
        if mode in ("rs232", "both") and rs232_poweron and rs232_standby:
            cmds += cmd_set_rs232_codes(
                rs232_poweron, rs232_standby, rs232_hex, rs232_param
            )
        await self.client.commands(cmds)

    async def async_check_available(self) -> bool:
        self.available = await self.client.async_test_connection()
        return self.available

    def as_device_registry_info(self) -> dict:
        """Return a dict suitable for HA DeviceInfo population."""
        return {
            "manufacturer": MANUFACTURER,
            "model": self.model or self.model_prefix or "AV Access device",
            "name": self.device_info_name(),
            "sw_version": self.firmware,
        }
