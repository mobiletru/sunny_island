"""Config + options flow for Tesla EVTV BMS (LiteCAN UDP + optional SMA WebBox).

Pack and WebBox settings live in ``entry.data`` (one bag). Setup, reconfigure,
and options all call ``normalize_entry_data`` so there is a single write shape.
"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_PORT,
    CONF_ENTITY_PREFIX,
    CONF_PACK_SIZE,
    CONF_CELLS_IN_SERIES,
    CONF_MIN_CELL_VOLTS,
    CONF_MAX_CELL_VOLTS,
    CONF_WEBBOX_HOST,
    CONF_WEBBOX_PASSWORD,
    CONF_WEBBOX_SCAN_INTERVAL,
    CONF_WEBBOX_MODBUS,
    CONF_WEBBOX_MODBUS_PORT,
    CONF_WEBBOX_UNIT_GATEWAY,
    CONF_WEBBOX_UNIT_PLANT,
    CONF_WEBBOX_UNIT_DEVICE,
    DEFAULT_PORT,
    DEFAULT_ENTITY_PREFIX,
    DEFAULT_PACK_SIZE,
    DEFAULT_CELLS_IN_SERIES,
    DEFAULT_MIN_CELL_VOLTS,
    DEFAULT_MAX_CELL_VOLTS,
    DEFAULT_WEBBOX_SCAN_INTERVAL,
    DEFAULT_WEBBOX_MODBUS,
    DEFAULT_WEBBOX_MODBUS_PORT,
    DEFAULT_WEBBOX_UNIT_GATEWAY,
    DEFAULT_WEBBOX_UNIT_PLANT,
    DEFAULT_WEBBOX_UNIT_DEVICE,
    normalize_entry_data,
)


def _schema(*, include_port: bool = True, defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    fields: dict = {
        vol.Required(CONF_NAME, default=d.get(CONF_NAME, "Tesla Pack")): str,
    }
    if include_port:
        fields[vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT))] = (
            vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))
        )
    fields.update(
        {
            vol.Required(
                CONF_ENTITY_PREFIX,
                default=d.get(CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX),
            ): str,
            vol.Required(
                CONF_PACK_SIZE, default=d.get(CONF_PACK_SIZE, DEFAULT_PACK_SIZE)
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10000)),
            vol.Required(
                CONF_CELLS_IN_SERIES,
                default=d.get(CONF_CELLS_IN_SERIES, DEFAULT_CELLS_IN_SERIES),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
            vol.Required(
                CONF_MIN_CELL_VOLTS,
                default=d.get(CONF_MIN_CELL_VOLTS, DEFAULT_MIN_CELL_VOLTS),
            ): vol.Coerce(float),
            vol.Required(
                CONF_MAX_CELL_VOLTS,
                default=d.get(CONF_MAX_CELL_VOLTS, DEFAULT_MAX_CELL_VOLTS),
            ): vol.Coerce(float),
            vol.Optional(
                CONF_WEBBOX_HOST,
                default=d.get(CONF_WEBBOX_HOST) or "",
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    autocomplete="off",
                )
            ),
            vol.Optional(
                CONF_WEBBOX_PASSWORD,
                default=d.get(CONF_WEBBOX_PASSWORD) or "",
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.PASSWORD,
                    autocomplete="off",
                )
            ),
            vol.Optional(
                CONF_WEBBOX_SCAN_INTERVAL,
                default=d.get(
                    CONF_WEBBOX_SCAN_INTERVAL, DEFAULT_WEBBOX_SCAN_INTERVAL
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            vol.Optional(
                CONF_WEBBOX_MODBUS,
                default=d.get(CONF_WEBBOX_MODBUS, DEFAULT_WEBBOX_MODBUS),
            ): bool,
            vol.Optional(
                CONF_WEBBOX_MODBUS_PORT,
                default=d.get(CONF_WEBBOX_MODBUS_PORT, DEFAULT_WEBBOX_MODBUS_PORT),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Optional(
                CONF_WEBBOX_UNIT_GATEWAY,
                default=d.get(CONF_WEBBOX_UNIT_GATEWAY, DEFAULT_WEBBOX_UNIT_GATEWAY),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=247)),
            vol.Optional(
                CONF_WEBBOX_UNIT_PLANT,
                default=d.get(CONF_WEBBOX_UNIT_PLANT, DEFAULT_WEBBOX_UNIT_PLANT),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=247)),
            vol.Optional(
                CONF_WEBBOX_UNIT_DEVICE,
                default=d.get(CONF_WEBBOX_UNIT_DEVICE, DEFAULT_WEBBOX_UNIT_DEVICE),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=247)),
        }
    )
    return vol.Schema(fields)


async def _apply_entry_data(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    user_input: dict,
) -> dict:
    """Normalize form input, write entry.data, reload. Shared by options path."""
    data = normalize_entry_data(
        user_input, existing=dict(entry.data), preserve_port=True
    )
    hass.config_entries.async_update_entry(
        entry, data=data, title=data[CONF_NAME]
    )
    await hass.config_entries.async_reload(entry.entry_id)
    return data


class TeslaEVTVBMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            data = normalize_entry_data(user_input)
            await self.async_set_unique_id(f"{DOMAIN}_{int(data[CONF_PORT])}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(include_port=True),
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            data = normalize_entry_data(
                user_input, existing=dict(entry.data), preserve_port=True
            )
            return self.async_update_reload_and_abort(
                entry,
                data_updates=data,
                title=data[CONF_NAME],
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(include_port=False, defaults=dict(entry.data)),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return TeslaEVTVBMSOptionsFlow()


class TeslaEVTVBMSOptionsFlow(config_entries.OptionsFlow):
    """Configure gear — same schema/merger as reconfigure; writes entry.data."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            await _apply_entry_data(self.hass, self.config_entry, user_input)
            # Options payload unused; all settings live in entry.data.
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                include_port=False, defaults=dict(self.config_entry.data)
            ),
        )
