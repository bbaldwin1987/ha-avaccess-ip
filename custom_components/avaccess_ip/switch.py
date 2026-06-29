"""Switch platform — display power for each decoder's attached display."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DISPLAY_PROFILE_SAMSUNG_FRAME, DOMAIN
from .coordinator import AVAccessCoordinator
from .entity import AVAccessEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AVAccessCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device in coordinator.decoders:
        entities.append(AVAccessDisplayPower(coordinator, device))
        if device.display_profile == DISPLAY_PROFILE_SAMSUNG_FRAME:
            entities.append(AVAccessSamsungFrameArtMode(coordinator, device))
    async_add_entities(entities)


class AVAccessDisplayPower(AVAccessEntity, SwitchEntity):
    """Turns the display attached to a decoder on/off via sinkpower.

    The device has no readback for the display's actual power state, so this is
    an optimistic, assumed-state switch (the last commanded state).
    """

    _attr_translation_key = "display_power"
    _attr_icon = "mdi:television"

    def __init__(self, coordinator: AVAccessCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.unique_id}_display_power"
        self._attr_name = "Display power"
        self._is_on: bool | None = None

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def assumed_state(self) -> bool:
        return True  # no power-state readback from the device

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._device.async_set_display_power(True)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.async_set_display_power(False)
        self._is_on = False
        self.async_write_ha_state()


class AVAccessSamsungFrameArtMode(AVAccessEntity, SwitchEntity):
    """Turns Samsung Frame Art Mode on/off through decoder RS232 Ex-Link."""

    _attr_translation_key = "samsung_frame_art_mode"
    _attr_icon = "mdi:image-frame"

    def __init__(self, coordinator: AVAccessCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.unique_id}_samsung_frame_art_mode"
        self._attr_name = "Samsung Frame Art Mode"
        self._is_on: bool | None = None

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def assumed_state(self) -> bool:
        return True  # Samsung Ex-Link Art Mode state is command-only here.

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._device.async_send_samsung_frame_art_mode(True)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.async_send_samsung_frame_art_mode(False)
        self._is_on = False
        self.async_write_ha_state()
