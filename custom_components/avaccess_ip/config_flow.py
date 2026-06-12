"""Config and options flow for AV Access IP.

Setup model: a single hub entry that you add devices into one at a time. The
user picks the device type (encoder/decoder) and enters its IP; we Telnet in to
verify and auto-classify before registering it. Add/remove/edit happen in the
options flow.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_CEC_POWERON,
    CONF_CEC_STANDBY,
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONF_ENABLE_BROADCAST,
    CONF_HOST,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_RS232_HEX,
    CONF_RS232_POWERON,
    CONF_RS232_STANDBY,
    CONF_SINKPOWER_MODE,
    DEFAULT_CEC_POWERON,
    DEFAULT_CEC_STANDBY,
    DEFAULT_ENABLE_BROADCAST,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SINKPOWER_MODE,
    DOMAIN,
    SINKPOWER_MODES,
    TYPE_DECODER,
    TYPE_ENCODER,
)
from .device import AVDevice

_LOGGER = logging.getLogger(__name__)

TYPE_CHOICES = {TYPE_ENCODER: "Encoder (TX)", TYPE_DECODER: "Decoder (RX)"}


async def _verify_device(host: str, expected_type: str) -> tuple[AVDevice | None, str | None]:
    """Telnet to a host and identify it. Returns (device, error_key)."""
    device = AVDevice(host=host, device_type=expected_type)
    try:
        await device.async_identify()
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Verify failed for %s: %s", host, err)
        return None, "cannot_connect"
    return device, None


class AVAccessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup — create the single hub entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the hub entry. Devices are added later via options."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="AV Access IP",
                data={CONF_DEVICES: []},
                options={
                    CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
                    CONF_ENABLE_BROADCAST: DEFAULT_ENABLE_BROADCAST,
                },
            )

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return AVAccessOptionsFlow(entry)


class AVAccessOptionsFlow(OptionsFlow):
    """Add/remove/edit devices and tune options."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._pending: dict[str, Any] = {}

    # -- menu ----------------------------------------------------------------
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_device", "remove_device", "settings"],
        )

    # -- add device ----------------------------------------------------------
    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            dtype = user_input[CONF_DEVICE_TYPE]
            if any(d[CONF_HOST] == host for d in self._devices()):
                errors["base"] = "already_configured"
            else:
                device, err = await _verify_device(host, dtype)
                if err:
                    errors["base"] = err
                else:
                    self._pending = {
                        CONF_HOST: host,
                        CONF_DEVICE_TYPE: device.device_type,
                        CONF_NAME: device.device_info_name(),
                    }
                    if device.is_decoder:
                        return await self.async_step_power_config()
                    return self._save_pending()

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_TYPE, default=TYPE_DECODER): vol.In(
                    TYPE_CHOICES
                ),
                vol.Required(CONF_HOST): str,
            }
        )
        return self.async_show_form(
            step_id="add_device", data_schema=schema, errors=errors
        )

    # -- per-decoder display power config -----------------------------------
    async def async_step_power_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._pending.update(user_input)
            return self._save_pending()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SINKPOWER_MODE, default=DEFAULT_SINKPOWER_MODE
                ): vol.In(SINKPOWER_MODES),
                vol.Optional(CONF_CEC_POWERON, default=DEFAULT_CEC_POWERON): str,
                vol.Optional(CONF_CEC_STANDBY, default=DEFAULT_CEC_STANDBY): str,
                vol.Optional(CONF_RS232_HEX, default=False): bool,
                vol.Optional(CONF_RS232_POWERON, default=""): str,
                vol.Optional(CONF_RS232_STANDBY, default=""): str,
            }
        )
        return self.async_show_form(step_id="power_config", data_schema=schema)

    # -- remove device -------------------------------------------------------
    async def async_step_remove_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            host = user_input[CONF_HOST]
            remaining = [d for d in devices if d[CONF_HOST] != host]
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, CONF_DEVICES: remaining}
            )
            return self.async_create_entry(title="", data=dict(self._entry.options))

        choices = {
            d[CONF_HOST]: f"{d.get(CONF_NAME, d[CONF_HOST])} ({d[CONF_HOST]})"
            for d in devices
        }
        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({vol.Required(CONF_HOST): vol.In(choices)}),
        )

    # -- settings ------------------------------------------------------------
    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        opts = self._entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=opts.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): vol.All(int, vol.Range(min=5, max=600)),
                vol.Required(
                    CONF_ENABLE_BROADCAST,
                    default=opts.get(
                        CONF_ENABLE_BROADCAST, DEFAULT_ENABLE_BROADCAST
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    # -- helpers -------------------------------------------------------------
    def _devices(self) -> list[dict[str, Any]]:
        return list(self._entry.data.get(CONF_DEVICES, []))

    def _save_pending(self) -> ConfigFlowResult:
        devices = self._devices()
        devices.append(self._pending)
        self.hass.config_entries.async_update_entry(
            self._entry, data={**self._entry.data, CONF_DEVICES: devices}
        )
        self._pending = {}
        return self.async_create_entry(title="", data=dict(self._entry.options))
