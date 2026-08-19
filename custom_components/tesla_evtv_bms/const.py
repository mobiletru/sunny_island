DOMAIN = "tesla_evtv_bms"
PLATFORMS = ["sensor", "select"]

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
CONF_WEBBOX_MODBUS = "webbox_modbus"
CONF_WEBBOX_MODBUS_PORT = "webbox_modbus_port"
CONF_WEBBOX_UNIT_GATEWAY = "webbox_unit_gateway"
CONF_WEBBOX_UNIT_PLANT = "webbox_unit_plant"
CONF_WEBBOX_UNIT_DEVICE = "webbox_unit_device"

SIGNAL_UPDATE_ENTITY = f"{DOMAIN}_{{}}_update"

DEFAULT_PORT = 6550
DEFAULT_ENTITY_PREFIX = "battery_storage_tesla_pack"
DEFAULT_PACK_SIZE = 75.0
# This plant: 2×6S modules in series = 12S (not total cells on the CAN bus).
DEFAULT_CELLS_IN_SERIES = 12
DEFAULT_MIN_CELL_VOLTS = 3.2
DEFAULT_MAX_CELL_VOLTS = 4.1
DEFAULT_WEBBOX_SCAN_INTERVAL = 10
DEFAULT_WEBBOX_MODBUS = True
DEFAULT_WEBBOX_MODBUS_PORT = 502
DEFAULT_WEBBOX_UNIT_GATEWAY = 1
DEFAULT_WEBBOX_UNIT_PLANT = 2
DEFAULT_WEBBOX_UNIT_DEVICE = 3

# HTTP overview + Modbus proxy parameters (all under WebBox device)
WEBBOX_SENSOR_KEYS = (
    "webbox_power",
    "webbox_power_kw",
    "webbox_daily_yield",
    "webbox_total_yield",
    "webbox_device_power",
    "webbox_grid_voltage",
    "webbox_grid_frequency",
    "webbox_reactive_power",
    "webbox_apparent_power",
    "webbox_status_code",
    "webbox_status",
    "webbox_grid_relay_code",
    "webbox_grid_relay",
    "webbox_grid_connection_time",
    "webbox_operating_status_code",
    "webbox_operating_status",
    "webbox_generator_status_code",
    "webbox_generator_status",
    "webbox_grid_control_code",
    "webbox_grid_control",
    "webbox_bat_typ",
    "webbox_battery_voltage",
    "webbox_battery_soc",
    "webbox_battery_temp",
    "webbox_battery_current",
    "webbox_discharge_limit",
    "webbox_reverse_feed_code",
    "webbox_reverse_feed",
    "webbox_feed_soc_upper",
    "webbox_feed_soc_lower",
    "webbox_power_setpoint_timeout",
    "webbox_power_setpoint_mode_code",
    "webbox_power_setpoint_mode",
    "webbox_operating_time",
    "webbox_serial",
    "webbox_device_serial",
    "webbox_modbus_profile",
    "webbox_device_susy_id",
    "webbox_rpc_status",
    "webbox_device_key",
    "webbox_charge_mode",
    "webbox_fault_text",
)

# Service: tesla_evtv_bms.set_grid_control
SERVICE_SET_GRID_CONTROL = "set_grid_control"
# Service: tesla_evtv_bms.set_si_parameter — write SI params from plant UI
# (RPC SetParameter for grid_control / bat_typ; Modbus for the rest)
SERVICE_SET_SI_PARAMETER = "set_si_parameter"
# set_si_parameter ids that use WebBox RPC SetParameter (not Modbus)
SI_RPC_PARAM_BAT_TYP = frozenset({"bat_typ", "battyp", "battery_type"})
SI_RPC_PARAM_GRID = frozenset({"grid_control", "grid", "gdmanstr"})
ATTR_MODE = "mode"
ATTR_PARAMETER = "parameter"
ATTR_VALUE = "value"
ATTR_DEVICE_ID = "device_id"
ATTR_ENTRY_ID = "entry_id"


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
    """Sanitize form / options values into entry.data shape."""
    base = dict(existing or {})
    base.update(user_input)

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

    # Modbus proxy defaults
    if CONF_WEBBOX_MODBUS not in base:
        base[CONF_WEBBOX_MODBUS] = DEFAULT_WEBBOX_MODBUS
    else:
        base[CONF_WEBBOX_MODBUS] = bool(base[CONF_WEBBOX_MODBUS])
    for key, default in (
        (CONF_WEBBOX_MODBUS_PORT, DEFAULT_WEBBOX_MODBUS_PORT),
        (CONF_WEBBOX_UNIT_GATEWAY, DEFAULT_WEBBOX_UNIT_GATEWAY),
        (CONF_WEBBOX_UNIT_PLANT, DEFAULT_WEBBOX_UNIT_PLANT),
        (CONF_WEBBOX_UNIT_DEVICE, DEFAULT_WEBBOX_UNIT_DEVICE),
    ):
        try:
            base[key] = int(base.get(key, default))
        except (TypeError, ValueError):
            base[key] = default

    if preserve_port and existing is not None and CONF_PORT in existing:
        base[CONF_PORT] = existing[CONF_PORT]
    elif CONF_PORT in base:
        base[CONF_PORT] = int(base[CONF_PORT])

    return base
