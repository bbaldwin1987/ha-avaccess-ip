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
    CONF_FIRMWARE,
    CONF_HOST,
    CONF_HOSTNAME,
    CONF_MAC,
    CONF_MODEL,
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
from .device import AVDevice, clean_alias

_LOGGER = logging.getLogger(__name__)

TYPE_CHOICES = {TYPE_ENCODER: "Encoder (TX)", TYPE_DECODER: "Decoder (RX)"}
ACTION_ADD_DEVICE = "add_device"
ACTION_EDIT_DEVICE = "edit_device"
ACTION_RENAME_DEVICE = "rename_device"
ACTION_REMOVE_DEVICE = "remove_device"
ACTION_SETTINGS = "settings"
ACTION_CHOICES = {
    ACTION_ADD_DEVICE: "Add a device",
    ACTION_EDIT_DEVICE: "Edit a device",
    ACTION_RENAME_DEVICE: "Rename a device",
    ACTION_REMOVE_DEVICE: "Remove a device",
    ACTION_SETTINGS: "Settings",
}


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
        if user_input is not None:
            action = user_input["action"]
            if action == ACTION_ADD_DEVICE:
                return await self.async_step_add_device()
            if action == ACTION_EDIT_DEVICE:
                return await self.async_step_edit_device()
            if action == ACTION_RENAME_DEVICE:
                return await self.async_step_rename_device()
            if action == ACTION_REMOVE_DEVICE:
                return await self.async_step_remove_device()
            if action == ACTION_SETTINGS:
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required("action", default=ACTION_ADD_DEVICE): vol.In(ACTION_CHOICES)}
            ),
        )

    # -- add device ----------------------------------------------------------
    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            dtype = user_input[CONF_DEVICE_TYPE]
            friendly_name = user_input[CONF_NAME].strip()
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
                        CONF_NAME: clean_alias(friendly_name) or device.device_info_name(),
                        CONF_HOSTNAME: device.hostname,
                        CONF_MAC: device.mac,
                        CONF_MODEL: device.model,
                        CONF_FIRMWARE: device.firmware,
                    }
                    return await self.async_step_confirm_device()

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_TYPE, default=TYPE_DECODER): vol.In(
                    TYPE_CHOICES
                ),
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="add_device", data_schema=schema, errors=errors
        )

    async def async_step_confirm_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the detected device identity before saving."""
        if user_input is not None:
            if not user_input.get("confirm", True):
                self._pending = {}
                return await self.async_step_init()
            if self._pending.get(CONF_DEVICE_TYPE) == TYPE_DECODER:
                return await self.async_step_power_config()
            return self._save_pending()

        schema = vol.Schema(
            {
                vol.Required("confirm", default=True): bool,
                vol.Optional(
                    "detected_name",
                    default=self._pending.get(CONF_NAME, "Unknown"),
                ): str,
                vol.Optional(
                    "detected_host",
                    default=self._pending.get(CONF_HOST, "Unknown"),
                ): str,
                vol.Optional(
                    "detected_type",
                    default=TYPE_CHOICES.get(
                        self._pending.get(CONF_DEVICE_TYPE), "Unknown"
                    ),
                ): str,
                vol.Optional(
                    "detected_hostname",
                    default=self._pending.get(CONF_HOSTNAME) or "Unknown",
                ): str,
                vol.Optional(
                    "detected_mac",
                    default=self._pending.get(CONF_MAC) or "Unknown",
                ): str,
                vol.Optional(
                    "detected_model",
                    default=self._pending.get(CONF_MODEL) or "Unknown",
                ): str,
                vol.Optional(
                    "detected_firmware",
                    default=self._pending.get(CONF_FIRMWARE) or "Unknown",
                ): str,
            }
        )
        return self.async_show_form(
            step_id="confirm_device",
            data_schema=schema,
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

    # -- edit/rename/remove device ------------------------------------------
    async def async_step_edit_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit IP, friendly name, and decoder power settings."""
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None and CONF_HOST not in self._pending:
            self._pending[CONF_HOST] = user_input[CONF_HOST]
            return await self.async_step_edit_device()

        if user_input is not None and CONF_NAME in user_input:
            original_host = self._pending.pop(CONF_HOST)
            host = user_input[CONF_HOST].strip()
            selected = next(d for d in devices if d[CONF_HOST] == original_host)

            if host != original_host and any(
                d[CONF_HOST] == host for d in devices if d[CONF_HOST] != original_host
            ):
                self._pending[CONF_HOST] = original_host
                return self.async_show_form(
                    step_id="edit_device",
                    data_schema=self._edit_device_schema(selected),
                    errors={"base": "already_configured"},
                )

            device, err = await _verify_device(host, selected[CONF_DEVICE_TYPE])
            if err:
                self._pending[CONF_HOST] = original_host
                return self.async_show_form(
                    step_id="edit_device",
                    data_schema=self._edit_device_schema(selected),
                    errors={"base": err},
                )

            updated_device = {
                **selected,
                CONF_HOST: host,
                CONF_DEVICE_TYPE: device.device_type,
                CONF_NAME: clean_alias(user_input[CONF_NAME].strip())
                or device.device_info_name(),
                CONF_HOSTNAME: device.hostname,
                CONF_MAC: device.mac,
                CONF_MODEL: device.model,
                CONF_FIRMWARE: device.firmware,
            }
            if device.is_decoder:
                updated_device.update(
                    {
                        CONF_SINKPOWER_MODE: user_input[CONF_SINKPOWER_MODE],
                        CONF_CEC_POWERON: user_input.get(
                            CONF_CEC_POWERON, DEFAULT_CEC_POWERON
                        ),
                        CONF_CEC_STANDBY: user_input.get(
                            CONF_CEC_STANDBY, DEFAULT_CEC_STANDBY
                        ),
                        CONF_RS232_HEX: user_input.get(CONF_RS232_HEX, False),
                        CONF_RS232_POWERON: user_input.get(CONF_RS232_POWERON, ""),
                        CONF_RS232_STANDBY: user_input.get(CONF_RS232_STANDBY, ""),
                    }
                )

            updated = [
                updated_device if d[CONF_HOST] == original_host else d for d in devices
            ]
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, CONF_DEVICES: updated}
            )
            return self.async_create_entry(title="", data=dict(self._entry.options))

        if CONF_HOST in self._pending:
            host = self._pending[CONF_HOST]
            selected = next(d for d in devices if d[CONF_HOST] == host)
            return self.async_show_form(
                step_id="edit_device",
                data_schema=self._edit_device_schema(selected),
            )

        choices = {
            d[CONF_HOST]: f"{d.get(CONF_NAME, d[CONF_HOST])} ({d[CONF_HOST]})"
            for d in devices
        }
        return self.async_show_form(
            step_id="edit_device",
            data_schema=vol.Schema({vol.Required(CONF_HOST): vol.In(choices)}),
        )

    async def async_step_rename_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rename a configured device in this integration."""
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None and CONF_HOST not in self._pending:
            self._pending[CONF_HOST] = user_input[CONF_HOST]
            return await self.async_step_rename_device()

        if user_input is not None and CONF_NAME in user_input:
            host = self._pending.pop(CONF_HOST)
            new_name = user_input[CONF_NAME].strip()
            updated = []
            for device in devices:
                if device[CONF_HOST] == host:
                    device = {**device, CONF_NAME: new_name}
                updated.append(device)
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, CONF_DEVICES: updated}
            )
            return self.async_create_entry(title="", data=dict(self._entry.options))

        if CONF_HOST in self._pending:
            host = self._pending[CONF_HOST]
            selected = next(d for d in devices if d[CONF_HOST] == host)
            return self.async_show_form(
                step_id="rename_device",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_NAME,
                            default=selected.get(CONF_NAME, selected[CONF_HOST]),
                        ): str,
                    }
                ),
            )

        choices = {
            d[CONF_HOST]: f"{d.get(CONF_NAME, d[CONF_HOST])} ({d[CONF_HOST]})"
            for d in devices
        }
        return self.async_show_form(
            step_id="rename_device",
            data_schema=vol.Schema({vol.Required(CONF_HOST): vol.In(choices)}),
        )

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

    def _edit_device_schema(self, device: dict[str, Any]) -> vol.Schema:
        schema: dict[Any, Any] = {
            vol.Required(CONF_HOST, default=device[CONF_HOST]): str,
            vol.Required(CONF_NAME, default=device.get(CONF_NAME, device[CONF_HOST])): str,
        }
        if device.get(CONF_DEVICE_TYPE) == TYPE_DECODER:
            schema.update(
                {
                    vol.Required(
                        CONF_SINKPOWER_MODE,
                        default=device.get(
                            CONF_SINKPOWER_MODE, DEFAULT_SINKPOWER_MODE
                        ),
                    ): vol.In(SINKPOWER_MODES),
                    vol.Optional(
                        CONF_CEC_POWERON,
                        default=device.get(CONF_CEC_POWERON, DEFAULT_CEC_POWERON),
                    ): str,
                    vol.Optional(
                        CONF_CEC_STANDBY,
                        default=device.get(CONF_CEC_STANDBY, DEFAULT_CEC_STANDBY),
                    ): str,
                    vol.Optional(
                        CONF_RS232_HEX,
                        default=device.get(CONF_RS232_HEX, False),
                    ): bool,
                    vol.Optional(
                        CONF_RS232_POWERON,
                        default=device.get(CONF_RS232_POWERON, ""),
                    ): str,
                    vol.Optional(
                        CONF_RS232_STANDBY,
                        default=device.get(CONF_RS232_STANDBY, ""),
                    ): str,
                }
            )
        return vol.Schema(schema)

    def _save_pending(self) -> ConfigFlowResult:
        devices = self._devices()
        devices.append(self._pending)
        self.hass.config_entries.async_update_entry(
            self._entry, data={**self._entry.data, CONF_DEVICES: devices}
        )
        self._pending = {}
        return self.async_create_entry(title="", data=dict(self._entry.options))
