from homeassistant import config_entries
import voluptuous as vol

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_PORT,
    CONF_WEBBOX_HOST,
    CONF_WEBBOX_PASSWORD,
    CONF_WEBBOX_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_PACK_SIZE,
    DEFAULT_CELLS_IN_SERIES,
    DEFAULT_MIN_CELL_VOLTS,
    DEFAULT_MAX_CELL_VOLTS,
    DEFAULT_WEBBOX_SCAN_INTERVAL,
)


class TeslaEVTVBMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
                vol.Required("pack_size", default=DEFAULT_PACK_SIZE): vol.Coerce(float),
                vol.Required("cells_in_series", default=DEFAULT_CELLS_IN_SERIES): vol.Coerce(int),
                vol.Required("min_cell_volts", default=DEFAULT_MIN_CELL_VOLTS): vol.Coerce(float),
                vol.Required("max_cell_volts", default=DEFAULT_MAX_CELL_VOLTS): vol.Coerce(float),
                vol.Optional(CONF_WEBBOX_HOST, default=""): str,
                vol.Optional(CONF_WEBBOX_PASSWORD, default=""): str,
                vol.Optional(CONF_WEBBOX_SCAN_INTERVAL, default=DEFAULT_WEBBOX_SCAN_INTERVAL): vol.Coerce(int),
            }),
            description_placeholders={
                "info": "Configure the Tesla EVTV BMS listener. "
                "Cells in series (S): two Tesla modules wired in series = 12. "
                "WebBox host is optional — leave blank to skip solar/WebBox sensors "
                "(e.g. 192.168.100.180, no http:// prefix).",
            },
        )