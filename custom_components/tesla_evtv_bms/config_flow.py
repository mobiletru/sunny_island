from homeassistant import config_entries
from homeassistant.core import callback
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
    DEFAULT_PORT,
    DEFAULT_ENTITY_PREFIX,
    DEFAULT_PACK_SIZE,
    DEFAULT_CELLS_IN_SERIES,
    DEFAULT_MIN_CELL_VOLTS,
    DEFAULT_MAX_CELL_VOLTS,
    DEFAULT_WEBBOX_SCAN_INTERVAL,
)
from .runtime import entity_prefix_from_data


def _user_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "Tesla Pack")): str,
            vol.Required(
                CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT)
            ): vol.Coerce(int),
            vol.Required(
                CONF_ENTITY_PREFIX,
                default=d.get(CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX),
            ): str,
            vol.Required(
                CONF_PACK_SIZE, default=d.get(CONF_PACK_SIZE, DEFAULT_PACK_SIZE)
            ): vol.Coerce(float),
            vol.Required(
                CONF_CELLS_IN_SERIES,
                default=d.get(CONF_CELLS_IN_SERIES, DEFAULT_CELLS_IN_SERIES),
            ): vol.Coerce(int),
            vol.Required(
                CONF_MIN_CELL_VOLTS,
                default=d.get(CONF_MIN_CELL_VOLTS, DEFAULT_MIN_CELL_VOLTS),
            ): vol.Coerce(float),
            vol.Required(
                CONF_MAX_CELL_VOLTS,
                default=d.get(CONF_MAX_CELL_VOLTS, DEFAULT_MAX_CELL_VOLTS),
            ): vol.Coerce(float),
            vol.Optional(
                CONF_WEBBOX_HOST, default=d.get(CONF_WEBBOX_HOST, "")
            ): str,
            vol.Optional(
                CONF_WEBBOX_PASSWORD, default=d.get(CONF_WEBBOX_PASSWORD, "")
            ): str,
            vol.Optional(
                CONF_WEBBOX_SCAN_INTERVAL,
                default=d.get(CONF_WEBBOX_SCAN_INTERVAL, DEFAULT_WEBBOX_SCAN_INTERVAL),
            ): vol.Coerce(int),
        }
    )


class TeslaEVTVBMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"{DOMAIN}_{port}")
            self._abort_if_unique_id_configured()

            user_input[CONF_ENTITY_PREFIX] = entity_prefix_from_data(user_input)
            return self.async_create_entry(
                title=user_input[CONF_NAME], data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
            description_placeholders={
                "info": "Configure the Tesla EVTV BMS listener. "
                "Entity prefix becomes sensor.<prefix>_<key> (match Sunny Island "
                "add-on pack_prefix). Cells in series (S): two Tesla modules in "
                "series = 12. WebBox host optional (no http:// prefix).",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TeslaEVTVBMSOptionsFlow(config_entry)


class TeslaEVTVBMSOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            user_input[CONF_ENTITY_PREFIX] = entity_prefix_from_data(
                {**self._config_entry.data, **user_input}
            )
            # Persist into entry data so PackRuntime sees them after reload
            new_data = {**self._config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(self._config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        data = self._config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=_user_schema(dict(data)),
        )
