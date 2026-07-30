DOMAIN = "tesla_evtv_bms"
PLATFORMS = ["sensor"]

CONF_NAME = "name"
CONF_PORT = "port"
CONF_ENTITY_PREFIX = "entity_prefix"
CONF_PACK_SIZE = "pack_size"
CONF_CELLS_IN_SERIES = "cells_in_series"
CONF_MIN_CELL_VOLTS = "min_cell_volts"
CONF_MAX_CELL_VOLTS = "max_cell_volts"
CONF_WEBBOX_HOST = "webbox_host"
CONF_WEBBOX_PASSWORD = "webbox_password"
CONF_WEBBOX_SCAN_INTERVAL = "webbox_scan_interval"

SIGNAL_UPDATE_ENTITY = f"{DOMAIN}_{{}}_update"

DEFAULT_PORT = 6550
DEFAULT_ENTITY_PREFIX = "battery_storage_tesla_pack"
DEFAULT_PACK_SIZE = 75.0
# This plant: 2×6S modules in series = 12S (not total cells on the CAN bus).
DEFAULT_CELLS_IN_SERIES = 12
DEFAULT_MIN_CELL_VOLTS = 3.2
DEFAULT_MAX_CELL_VOLTS = 4.1
DEFAULT_WEBBOX_SCAN_INTERVAL = 10

WEBBOX_SENSOR_KEYS = ("webbox_power", "webbox_daily_yield", "webbox_total_yield")


def pack_config_from_data(data: dict) -> dict:
    """Build runtime pack config from a config entry data dict."""
    return {
        "pack_size": data.get(CONF_PACK_SIZE, DEFAULT_PACK_SIZE),
        "cells_in_series": data.get(CONF_CELLS_IN_SERIES, DEFAULT_CELLS_IN_SERIES),
        "min_cell_volts": data.get(CONF_MIN_CELL_VOLTS, DEFAULT_MIN_CELL_VOLTS),
        "max_cell_volts": data.get(CONF_MAX_CELL_VOLTS, DEFAULT_MAX_CELL_VOLTS),
    }


def normalize_entry_data(
    user_input: dict,
    *,
    existing: dict | None = None,
    preserve_port: bool = False,
) -> dict:
    """Sanitize form / options values into entry.data shape.

    Single writer used by setup, reconfigure, and options flows.
    """
    base = dict(existing or {})
    base.update(user_input)

    # entity_prefix — keep import local-friendly for tests without HA
    from .runtime import entity_prefix_from_data

    base[CONF_ENTITY_PREFIX] = entity_prefix_from_data(base)

    host = (base.get(CONF_WEBBOX_HOST) or "").strip()
    host = host.removeprefix("http://").removeprefix("https://")
    host = host.split("/")[0].strip()
    base[CONF_WEBBOX_HOST] = host
    base[CONF_WEBBOX_PASSWORD] = (base.get(CONF_WEBBOX_PASSWORD) or "").strip()

    if CONF_WEBBOX_SCAN_INTERVAL in base:
        base[CONF_WEBBOX_SCAN_INTERVAL] = int(base[CONF_WEBBOX_SCAN_INTERVAL])
    else:
        base[CONF_WEBBOX_SCAN_INTERVAL] = DEFAULT_WEBBOX_SCAN_INTERVAL

    if preserve_port and existing is not None and CONF_PORT in existing:
        base[CONF_PORT] = existing[CONF_PORT]
    elif CONF_PORT in base:
        base[CONF_PORT] = int(base[CONF_PORT])

    return base
