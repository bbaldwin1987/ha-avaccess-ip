"""DataUpdateCoordinator for AV Access IP.

Owns the set of manually-added devices (membership is defined by the config
entry, not by discovery). Each refresh:

* probes each device's IP for reachability (marks available/unavailable), and
* for each decoder, reads its current bonded source so entity state reflects
  reality even when changed by the front panel or another controller.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .device import AVDevice

_LOGGER = logging.getLogger(__name__)


class AVAccessCoordinator(DataUpdateCoordinator[dict[str, AVDevice]]):
    """Coordinate polling across all configured AV Access devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        devices: dict[str, AVDevice],
        poll_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )
        self.entry = entry
        self.devices = devices

    @property
    def encoders(self) -> list[AVDevice]:
        return [d for d in self.devices.values() if d.is_encoder]

    @property
    def decoders(self) -> list[AVDevice]:
        return [d for d in self.devices.values() if d.is_decoder]

    def source_options(self) -> dict[str, str]:
        """Map encoder MAC -> friendly name, for decoder source lists."""
        return {
            d.mac: d.device_info_name()
            for d in self.encoders
            if d.mac
        }

    def encoder_by_mac(self, mac: str) -> AVDevice | None:
        for d in self.encoders:
            if d.mac and d.mac.lower() == mac.lower():
                return d
        return None

    def encoder_by_name(self, name: str) -> AVDevice | None:
        for d in self.encoders:
            if d.device_info_name() == name:
                return d
        return None

    async def _async_update_data(self) -> dict[str, AVDevice]:
        """Refresh availability and decoder source state for all devices."""

        async def _refresh(device: AVDevice) -> None:
            try:
                if not device.available or device.firmware is None:
                    # (re)identify if we have never succeeded or it dropped
                    await device.async_identify()
                else:
                    await device.async_check_available()
                    if device.is_decoder and device.available:
                        await device.async_update_source()
            except Exception as err:  # noqa: BLE001 — keep other devices alive
                device.available = False
                _LOGGER.debug("Refresh failed for %s: %s", device.host, err)

        await asyncio.gather(*(_refresh(d) for d in self.devices.values()))
        return self.devices
