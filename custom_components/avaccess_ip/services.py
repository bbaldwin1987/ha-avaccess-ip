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

_SCHEMA = vol.Schema(
    {
        vol.Required("target"): cv.entity_ids,
        vol.Required("source"): cv.string,
    }
)


def _find_coordinators(hass: HomeAssistant) -> list[AVAccessCoordinator]:
    return list(hass.data.get(DOMAIN, {}).values())


async def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SWITCH_GROUP):
        return

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

    hass.services.async_register(
        DOMAIN, SERVICE_SWITCH_GROUP, _handle_switch_group, schema=_SCHEMA
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SWITCH_GROUP):
        hass.services.async_remove(DOMAIN, SERVICE_SWITCH_GROUP)


def _resolve_decoders(hass, coordinators, entity_ids):
    """Map media_player entity_ids back to AVDevice decoder objects."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    devices = []
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        if not entry or not entry.unique_id:
            continue
        # unique_id format: "<device.unique_id>_media_player"
        base = entry.unique_id.rsplit("_media_player", 1)[0]
        for coord in coordinators:
            for dev in coord.decoders:
                if dev.unique_id == base:
                    devices.append(dev)
    return devices


_session_counter = 0


def _next_session() -> int:
    """Monotonically increasing session number for msg_b_reconnect."""
    global _session_counter
    _session_counter += 1
    return _session_counter
