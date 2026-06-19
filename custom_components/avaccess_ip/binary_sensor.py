"""Binary sensor platform for AV Access IP devices."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AVAccessCoordinator
from .entity import AVAccessEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up online status sensors for all configured devices."""
    coordinator: AVAccessCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AVAccessOnlineSensor(coordinator, device)
        for device in coordinator.devices.values()
    )


class AVAccessOnlineSensor(AVAccessEntity, BinarySensorEntity):
    """Diagnostic connectivity sensor for an AV Access device."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"
    _attr_name = "Online"

    def __init__(self, coordinator: AVAccessCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.unique_id}_online"

    @property
    def is_on(self) -> bool:
        """Return whether the device is currently reachable."""
        return self._device.available
