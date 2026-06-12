"""Diagnostics support for AV Access IP."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AVAccessCoordinator

# IPs are mildly sensitive; redact host but keep structure.
TO_REDACT = {"host"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: AVAccessCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _device_dump(dev) -> dict[str, Any]:
        return {
            "device_type": dev.device_type,
            "model": dev.model,
            "model_prefix": dev.model_prefix,
            "is_4k": dev.is_4k,
            "firmware": dev.firmware,
            "mac": dev.mac,
            "available": dev.available,
            "current_source_mac": dev.current_source_mac,
        }

    return {
        "options": dict(entry.options),
        "device_count": len(coordinator.devices),
        "encoders": [_device_dump(d) for d in coordinator.encoders],
        "decoders": [_device_dump(d) for d in coordinator.decoders],
    }
