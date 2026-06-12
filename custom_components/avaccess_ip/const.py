"""Constants for the AV Access IP integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "avaccess_ip"

# --- Telnet transport ---------------------------------------------------------
TELNET_PORT: Final = 24
LOGIN_USER: Final = "root"
PROMPT: Final = b"/#"
CONNECT_TIMEOUT: Final = 10.0
COMMAND_TIMEOUT: Final = 10.0

# --- UDP ports (from API Command Guide V1.0.3) --------------------------------
DISCOVERY_PROBE_PORT: Final = 3335     # client -> devices (probe)
DISCOVERY_REPLY_PORT: Final = 3336     # devices -> client (reply)
GROUP_SWITCH_PORT: Final = 5010        # client -> devices (msg_b_reconnect)
MRX_NOTIFY_PORT: Final = 11002         # MRX -> client (layout change; future)

# --- Config entry / options keys ----------------------------------------------
CONF_DEVICES: Final = "devices"
CONF_DEVICE_TYPE: Final = "device_type"
CONF_HOST: Final = "host"
CONF_NAME: Final = "name"
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_ENABLE_BROADCAST: Final = "enable_broadcast"

# per-decoder display power config keys
CONF_SINKPOWER_MODE: Final = "sinkpower_mode"
CONF_CEC_POWERON: Final = "cec_poweron_cmd"
CONF_CEC_STANDBY: Final = "cec_standby_cmd"
CONF_RS232_HEX: Final = "rs232_hex_enable"
CONF_RS232_POWERON: Final = "rs232_poweron_cmd"
CONF_RS232_STANDBY: Final = "rs232_standby_cmd"

# --- Device types -------------------------------------------------------------
TYPE_ENCODER: Final = "encoder"   # TX
TYPE_DECODER: Final = "decoder"   # RX
TYPE_MRX: Final = "mrx"           # 4KIP200M (future)

# --- Defaults -----------------------------------------------------------------
DEFAULT_POLL_INTERVAL: Final = 30          # seconds
DEFAULT_ENABLE_BROADCAST: Final = True
DEFAULT_SINKPOWER_MODE: Final = "cec"
DEFAULT_CEC_POWERON: Final = "40 04"
DEFAULT_CEC_STANDBY: Final = "ff 36"

SINKPOWER_MODES: Final = ["cec", "rs232", "both"]

# --- Model prefix -> (type, friendly model name, is_4k) -----------------------
# Response prefix as seen from the device (per guide section 1).
MODEL_MAP: Final = {
    "IPE935": (TYPE_ENCODER, "4KIP200E", True),
    "IPE9354": (TYPE_ENCODER, "4KIP204E", True),
    "IPD935": (TYPE_DECODER, "4KIP200D", True),
    "IPM4000": (TYPE_MRX, "4KIP200M", True),
    "IPE915": (TYPE_ENCODER, "HDIP100E", False),
    "IPD915": (TYPE_DECODER, "HDIP100D", False),
}

MANUFACTURER: Final = "AV Access"

# Special source value meaning "unbound"
SOURCE_NULL: Final = "NULL"
