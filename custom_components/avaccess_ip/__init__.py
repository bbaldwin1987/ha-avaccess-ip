"""The AV Access IP integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONF_HOST,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .coordinator import AVAccessCoordinator
from .device import AVDevice
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.SWITCH]


def _build_devices(entry: ConfigEntry) -> dict[str, AVDevice]:
    """Construct AVDevice objects from the config entry's device list."""
    devices: dict[str, AVDevice] = {}
    for item in entry.data.get(CONF_DEVICES, []):
        host = item[CONF_HOST]
        device = AVDevice(
            host=host,
            device_type=item.get(CONF_DEVICE_TYPE, "decoder"),
            alias=item.get(CONF_NAME),
        )
        devices[host] = device
    return devices


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AV Access IP from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    devices = _build_devices(entry)
    poll_interval = entry.options.get(
        CONF_POLL_INTERVAL,
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )

    coordinator = AVAccessCoordinator(hass, entry, devices, poll_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options (or the device list) change."""
    await hass.config_entries.async_reload(entry.entry_id)
