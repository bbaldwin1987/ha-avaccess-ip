"""Media player platform — each decoder is a source-selectable output."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AVAccessCoordinator
from .entity import AVAccessEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AVAccessCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AVAccessMediaPlayer(coordinator, device)
        for device in coordinator.decoders
    )


class AVAccessMediaPlayer(AVAccessEntity, MediaPlayerEntity):
    """A decoder presented as a media_player with source selection only."""

    _attr_icon = "mdi:video-input-hdmi"
    _attr_name = None  # use the device name
    _attr_supported_features = (
        MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: AVAccessCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.unique_id}_media_player"

    @property
    def state(self) -> MediaPlayerState:
        if not self._device.available:
            return MediaPlayerState.OFF
        if self._device.current_source_mac:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def source_list(self) -> list[str]:
        return sorted(self.coordinator.source_options().values())

    @property
    def source(self) -> str | None:
        mac = self._device.current_source_mac
        if not mac:
            return None
        return self.coordinator.source_options().get(mac, mac)

    async def async_select_source(self, source: str) -> None:
        """Route the chosen encoder to this decoder (bonded A/V/RS232)."""
        _LOGGER.debug(
            "Selecting source %s for decoder %s (%s)",
            source,
            self._device.device_info_name(),
            self._device.host,
        )
        encoder = self.coordinator.encoder_by_name(source)
        if encoder is None or not encoder.mac:
            _LOGGER.warning(
                "Unknown source %s for %s. Available sources: %s",
                source,
                self.entity_id,
                sorted(self.coordinator.source_options().values()),
            )
            return
        await self._device.async_set_source(encoder.mac)
        _LOGGER.debug(
            "Selected source %s (%s) for decoder %s (%s)",
            encoder.device_info_name(),
            encoder.mac,
            self._device.device_info_name(),
            self._device.host,
        )
        self.async_write_ha_state()  # optimistic; confirmed next poll

    async def async_turn_off(self) -> None:
        """Unbind the source (no signal to the display)."""
        await self._device.async_clear_source()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Re-bind the most recent source if known; else no-op."""
        # Without history we cannot know the prior source; users select one.
        self.async_write_ha_state()
