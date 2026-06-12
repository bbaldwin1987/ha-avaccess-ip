"""Shared base entity for AV Access IP."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AVAccessCoordinator
from .device import AVDevice


class AVAccessEntity(CoordinatorEntity[AVAccessCoordinator]):
    """Base entity tied to one AV Access device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AVAccessCoordinator, device: AVDevice) -> None:
        super().__init__(coordinator)
        self._device = device

    @property
    def device(self) -> AVDevice:
        return self._device

    @property
    def available(self) -> bool:
        return super().available and self._device.available

    @property
    def device_info(self) -> DeviceInfo:
        info = self._device.as_device_registry_info()
        connections = set()
        if self._device.mac:
            # format MAC as colon-separated for HA's connection set
            mac = self._device.mac
            pretty = ":".join(mac[i : i + 2] for i in range(0, len(mac), 2)).lower()
            connections = {("mac", pretty)}
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.unique_id)},
            connections=connections,
            manufacturer=info["manufacturer"],
            model=info["model"],
            name=info["name"],
            sw_version=info["sw_version"],
        )
