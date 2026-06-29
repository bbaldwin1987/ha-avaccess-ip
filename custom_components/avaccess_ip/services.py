"""Services for AV Access IP.

``avaccess_ip.switch_group`` switches several decoders to one encoder source at
once. When broadcast is enabled (and HA shares the device subnet) it sends a
single UDP ``msg_b_reconnect`` on port 5010; otherwise it falls back to issuing
the bonded ``--source-select`` + ``e e_reconnect`` to each decoder in turn.
"""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ENABLE_BROADCAST,
    DEFAULT_ENABLE_BROADCAST,
    DOMAIN,
)
from .coordinator import AVAccessCoordinator
from .transport import async_send_group_switch

_LOGGER = logging.getLogger(__name__)

SERVICE_SWITCH_GROUP = "switch_group"
SERVICE_CLEAR_SOURCE = "clear_source"
SERVICE_SEND_CEC = "send_cec"
SERVICE_REBOOT_DEVICE = "reboot_device"
SERVICE_SAMSUNG_FRAME_ART_MODE = "samsung_frame_art_mode"

_SWITCH_GROUP_SCHEMA = vol.Schema(
    {
        vol.Required("target"): cv.entity_ids,
        vol.Required("source"): cv.string,
    }
)
_ENTITY_TARGET_SCHEMA = vol.Schema({vol.Required("target"): cv.entity_ids})
_SEND_CEC_SCHEMA = vol.Schema(
    {
        vol.Required("target"): cv.entity_ids,
        vol.Required("cec_string"): cv.string,
    }
)
_SAMSUNG_FRAME_ART_MODE_SCHEMA = vol.Schema(
    {
        vol.Required("target"): cv.entity_ids,
        vol.Required("enabled"): cv.boolean,
    }
)


def _find_coordinators(hass: HomeAssistant) -> list[AVAccessCoordinator]:
    return list(hass.data.get(DOMAIN, {}).values())


async def async_setup_services(hass: HomeAssistant) -> None:
    async def _handle_switch_group(call: ServiceCall) -> None:
        target_entities: list[str] = call.data["target"]
        source: str = call.data["source"]

        coordinators = _find_coordinators(hass)
        if not coordinators:
            _LOGGER.warning("switch_group called but no AV Access hub is set up")
            return

        # Resolve the source encoder across all coordinators.
        encoder = None
        coordinator = coordinators[0]
        for coord in coordinators:
            encoder = coord.encoder_by_name(source) or coord.encoder_by_mac(source)
            if encoder:
                coordinator = coord
                break
        if encoder is None or not encoder.mac or not encoder.hostname:
            _LOGGER.error("switch_group: unknown source %s", source)
            return

        # Resolve target decoders from their media_player entity_ids.
        ent_reg_decoders = _resolve_decoders(hass, coordinators, target_entities)
        if not ent_reg_decoders:
            _LOGGER.error("switch_group: no matching decoders for %s", target_entities)
            return

        use_broadcast = coordinator.entry.options.get(
            CONF_ENABLE_BROADCAST, DEFAULT_ENABLE_BROADCAST
        )

        if use_broadcast and all(d.hostname for d in ent_reg_decoders):
            session = _next_session()
            await async_send_group_switch(
                tx_name=encoder.hostname,
                rx_names=[d.hostname for d in ent_reg_decoders],
                session_number=session,
            )
            # Optimistically update local state; poll will confirm.
            for d in ent_reg_decoders:
                d.current_source_mac = encoder.mac
        else:
            # Sequential fallback.
            await asyncio.gather(
                *(d.async_set_source(encoder.mac) for d in ent_reg_decoders)
            )

        for coord in coordinators:
            coord.async_update_listeners()

    async def _handle_clear_source(call: ServiceCall) -> None:
        coordinators = _find_coordinators(hass)
        decoders = _resolve_decoders(hass, coordinators, call.data["target"])
        if not decoders:
            _LOGGER.error("clear_source: no matching decoders for %s", call.data["target"])
            return
        await asyncio.gather(*(d.async_clear_source() for d in decoders))
        for coord in coordinators:
            coord.async_update_listeners()

    async def _handle_send_cec(call: ServiceCall) -> None:
        coordinators = _find_coordinators(hass)
        devices = _resolve_devices(hass, coordinators, call.data["target"])
        if not devices:
            _LOGGER.error("send_cec: no matching devices for %s", call.data["target"])
            return
        await asyncio.gather(
            *(d.async_send_cec(call.data["cec_string"]) for d in devices)
        )

    async def _handle_reboot_device(call: ServiceCall) -> None:
        coordinators = _find_coordinators(hass)
        devices = _resolve_devices(hass, coordinators, call.data["target"])
        if not devices:
            _LOGGER.error(
                "reboot_device: no matching devices for %s", call.data["target"]
            )
            return
        await asyncio.gather(*(d.async_reboot() for d in devices))

    async def _handle_samsung_frame_art_mode(call: ServiceCall) -> None:
        coordinators = _find_coordinators(hass)
        decoders = _resolve_decoders(hass, coordinators, call.data["target"])
        if not decoders:
            _LOGGER.error(
                "samsung_frame_art_mode: no matching decoders for %s",
                call.data["target"],
            )
            return
        await asyncio.gather(
            *(d.async_send_samsung_frame_art_mode(call.data["enabled"]) for d in decoders)
        )

    service_defs = {
        SERVICE_SWITCH_GROUP: (_handle_switch_group, _SWITCH_GROUP_SCHEMA),
        SERVICE_CLEAR_SOURCE: (_handle_clear_source, _ENTITY_TARGET_SCHEMA),
        SERVICE_SEND_CEC: (_handle_send_cec, _SEND_CEC_SCHEMA),
        SERVICE_REBOOT_DEVICE: (_handle_reboot_device, _ENTITY_TARGET_SCHEMA),
        SERVICE_SAMSUNG_FRAME_ART_MODE: (
            _handle_samsung_frame_art_mode,
            _SAMSUNG_FRAME_ART_MODE_SCHEMA,
        ),
    }
    for service, (handler, schema) in service_defs.items():
        if not hass.services.has_service(DOMAIN, service):
            hass.services.async_register(DOMAIN, service, handler, schema=schema)


async def async_unload_services(hass: HomeAssistant) -> None:
    for service in (
        SERVICE_SWITCH_GROUP,
        SERVICE_CLEAR_SOURCE,
        SERVICE_SEND_CEC,
        SERVICE_REBOOT_DEVICE,
        SERVICE_SAMSUNG_FRAME_ART_MODE,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


def _resolve_decoders(hass, coordinators, entity_ids):
    """Map media_player entity_ids back to AVDevice decoder objects."""
    return [d for d in _resolve_devices(hass, coordinators, entity_ids) if d.is_decoder]


def _resolve_devices(hass, coordinators, entity_ids):
    """Map AV Access entity_ids back to AVDevice objects."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    devices = []
    seen = set()
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        if not entry or not entry.unique_id:
            continue
        base = entry.unique_id
        for suffix in ("_media_player", "_display_power", "_online"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        for coord in coordinators:
            for dev in coord.devices.values():
                if dev.unique_id == base and dev.unique_id not in seen:
                    seen.add(dev.unique_id)
                    devices.append(dev)
    return devices


_session_counter = 0


def _next_session() -> int:
    """Monotonically increasing session number for msg_b_reconnect."""
    global _session_counter
    _session_counter += 1
    return _session_counter
