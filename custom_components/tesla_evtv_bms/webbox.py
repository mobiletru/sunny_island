"""Poll an SMA Sunny WebBox for plant overview + SI process data.

Transports (priority order):

1. ``POST /rpc`` with **form field** ``RPC=<json>`` (SMA WebBox RPC v1.0).
   Raw JSON body is **not** accepted on many firmware builds — they return
   the HTML frameset. Password is MD5-hashed into ``passwd``.
2. ``GET /home.ajax`` — no auth fallback for Power / DailyYield / TotalYield.

Process data from the first Sunny Island device fills battery / grid / status
sensors when Modbus is unavailable or as a second source.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

try:
    from aiohttp import ClientTimeout
except ImportError:  # pragma: no cover
    ClientTimeout = None  # type: ignore[misc, assignment]

_LOGGER = logging.getLogger(__name__)

RPC_VERSION = "1.0"

# home.ajax "Items" key -> our sensor key
OVERVIEW_KEY_MAP = {
    "Power": "webbox_power",
    "DailyYield": "webbox_daily_yield",
    "TotalYield": "webbox_total_yield",
}

# GetPlantOverview meta tags -> our sensor keys
RPC_OVERVIEW_MAP = {
    "GriPwr": "webbox_power",
    "Power": "webbox_power",
    "GriEgyTdy": "webbox_daily_yield",
    "DailyYield": "webbox_daily_yield",
    "GriEgyTot": "webbox_total_yield",
    "TotalYield": "webbox_total_yield",
}

# GetProcessData channel meta -> our sensor keys (numeric or text)
# kind: float | float_kw (×1000 → W) | text
RPC_PROCESS_MAP = {
    "BatSoc": ("webbox_battery_soc", "float"),
    "BatVtg": ("webbox_battery_voltage", "float"),
    "BatTmp": ("webbox_battery_temp", "float"),
    "InvPwrAt": ("webbox_device_power", "float_kw"),  # SI reports kW
    "Pac": ("webbox_device_power", "float_kw"),
    "ExtVtg": ("webbox_grid_voltage", "float"),
    "ExtFrq": ("webbox_grid_frequency", "float"),
    "Fac": ("webbox_grid_frequency", "float"),
    # Do not map ExtPwrAt → plant power (overwrites GriPwr with 0 when idle)
    "GdRmgTm": ("webbox_grid_connection_time", "float"),
    "GnRmgTm": ("webbox_grid_connection_time", "float"),
    "OpStt": ("webbox_operating_status", "text"),
    "Mode": ("webbox_operating_status", "text"),
    "GnStt": ("webbox_generator_status", "text"),
    "InvOpStt": ("webbox_status", "text"),
    "Error": ("webbox_fault_text", "text"),
    "BatChrgOp": ("webbox_charge_mode", "text"),
    "BatChrgVtg": ("webbox_charge_voltage", "float"),
}

# SI parameter: manual utility-grid start (GetParameter / SetParameter).
# On SI6048UM + WebBox, Modbus holding 40527 is illegal (exception 0x02); this
# RPC channel is the working control: Start | Auto | Stop.
GRID_MAN_STR_CHANNEL = "GdManStr"
GRID_MAN_STR_VALUES = ("Start", "Auto", "Stop")

# mode id → RPC GdManStr value  ·  RPC value → mode id
# mode ids match plant UI / set_grid_control service / select entity
OPTION_TO_GRID_MAN_STR: dict[str, str] = {
    "manual_on": "Start",
    "automatic": "Auto",
    "off": "Stop",
}
GRID_MAN_STR_TO_OPTION: dict[str, str] = {
    "Start": "manual_on",
    "Auto": "automatic",
    "Stop": "off",
}
# Synthetic codes kept for webbox_grid_control_code sensor compatibility
# (legacy Modbus enum 303/308/1438 when that path worked).
GRID_MAN_STR_TO_CODE: dict[str, int] = {
    "Start": 308,
    "Auto": 1438,
    "Stop": 303,
}
GRID_MAN_STR_LABELS: dict[str, str] = {
    "Start": "Manual On",
    "Auto": "Automatic",
    "Stop": "Off",
}

# SI6048UM GetParameter / SetParameter map (WebBox RPC).
# Per-cell charge voltages are 2 V VRLA cells (×24 ≈ pack V).
RPC_PARAM_SPECS: dict[str, dict[str, Any]] = {
    "charge_voltage_full": {
        "channel": "ChrgVtgFul",
        "sensor": "webbox_charge_voltage_full",
        "kind": "float",
        "min": 1.5,
        "max": 2.7,
        "decimals": 2,
    },
    "charge_voltage_float": {
        "channel": "ChrgVtgFlo",
        "sensor": "webbox_charge_voltage_float",
        "kind": "float",
        "min": 1.4,
        "max": 2.4,
        "decimals": 2,
    },
    "charge_voltage_boost": {
        "channel": "ChrgVtgBoost",
        "sensor": "webbox_charge_voltage_boost",
        "kind": "float",
        "min": 1.5,
        "max": 2.7,
        "decimals": 2,
    },
    "charge_voltage_equalize": {
        "channel": "ChrgVtgEqu",
        "sensor": "webbox_charge_voltage_equalize",
        "kind": "float",
        "min": 1.5,
        "max": 2.7,
        "decimals": 2,
    },
    "charge_voltage_manual": {
        "channel": "BatChrgVtgMan",
        "sensor": "webbox_charge_voltage_manual",
        "kind": "int",
        "min": 41,
        "max": 63,
    },
    "charge_current_max": {
        "channel": "BatChrgCurMax",
        "sensor": "webbox_charge_current_max",
        "kind": "int",
        "min": 10,
        "max": 1200,
    },
    "inverter_charge_current_max": {
        "channel": "InvChrgCurMax",
        "sensor": "webbox_inverter_charge_current_max",
        "kind": "int",
        "min": 0,
        "max": 50,
    },
    "charge_control": {
        "channel": "ChrgCtlOp",
        "sensor": "webbox_charge_control",
        "kind": "enum",
        "options": {"auto": "Auto", "manual": "Manual", "off": "Off"},
    },
    "auto_equalize": {
        "channel": "AutoEquChrgEna",
        "sensor": "webbox_auto_equalize",
        "kind": "enum",
        "options": {"enable": "Enable", "disable": "Disable"},
    },
    "absorption_time_boost": {
        "channel": "AptTmBoost",
        "sensor": "webbox_absorption_time_boost",
        "kind": "int",
        "min": 1,
        "max": 600,
    },
    "absorption_time_equalize": {
        "channel": "AptTmEqu",
        "sensor": "webbox_absorption_time_equalize",
        "kind": "int",
        "min": 1,
        "max": 48,
    },
    "absorption_time_full": {
        "channel": "AptTmFul",
        "sensor": "webbox_absorption_time_full",
        "kind": "int",
        "min": 1,
        "max": 20,
    },
    "battery_type": {
        "channel": "BatTyp",
        "sensor": "webbox_battery_type",
        "kind": "text",
        "readonly": True,
    },
    "battery_nominal_v": {
        "channel": "BatVtgNom",
        "sensor": "webbox_battery_nominal_v",
        "kind": "int",
        "min": 42,
        "max": 52,
    },
    "battery_capacity_ah": {
        "channel": "BatCpyNom",
        "sensor": "webbox_battery_capacity_ah",
        "kind": "int",
        "min": 100,
        "max": 10000,
    },
    "self_consumption_min": {
        "channel": "SlfCsmpSOCMin",
        "sensor": "webbox_self_consumption_min",
        "kind": "int",
        "min": 5,
        "max": 90,
    },
    "silent_enable": {
        "channel": "SilentEna",
        "sensor": "webbox_silent_enable",
        "kind": "enum",
        "options": {"enable": "Enable", "disable": "Disable"},
    },
    "sleep_enable": {
        "channel": "SleepEna",
        "sensor": "webbox_sleep_enable",
        "kind": "enum",
        "options": {"enable": "Enable", "disable": "Disable"},
    },
    "grid_current_nom": {
        "channel": "GdCurNom",
        "sensor": "webbox_grid_current_nom",
        "kind": "int",
        "min": 0,
        "max": 1000,
    },
    "grid_voltage_min": {
        "channel": "GdVtgMin",
        "sensor": "webbox_grid_voltage_min",
        "kind": "int",
        "min": 80,
        "max": 132,
    },
    "grid_voltage_max": {
        "channel": "GdVtgMax",
        "sensor": "webbox_grid_voltage_max",
        "kind": "int",
        "min": 105,
        "max": 150,
    },
    "grid_mode": {
        "channel": "GdMod",
        "sensor": "webbox_grid_mode",
        "kind": "text",
        "readonly": True,
    },
    "feed_in_mode": {
        "channel": "FedInMod",
        "sensor": "webbox_feed_in_mode",
        "kind": "text",
        "readonly": True,
    },
    "feed_in_soc_start": {
        "channel": "FedInSocStr",
        "sensor": "webbox_feed_in_soc_start",
        "kind": "int",
        "min": 1,
        "max": 90,
    },
    "feed_in_soc_stop": {
        "channel": "FedInSocStp",
        "sensor": "webbox_feed_in_soc_stop",
        "kind": "int",
        "min": 1,
        "max": 90,
    },
    "feed_in_current": {
        "channel": "FedInCurAt",
        "sensor": "webbox_feed_in_current",
        "kind": "int",
        "min": -1000,
        "max": 1000,
    },
    "cycle_time_equalize": {
        "channel": "CycTmEqu",
        "sensor": "webbox_cycle_time_equalize",
        "kind": "int",
        "min": 7,
        "max": 365,
    },
    "cycle_time_full": {
        "channel": "CycTmFul",
        "sensor": "webbox_cycle_time_full",
        "kind": "int",
        "min": 1,
        "max": 180,
    },
    "battery_temp_max": {
        "channel": "BatTmpMax",
        "sensor": "webbox_battery_temp_max",
        "kind": "int",
        "min": 0,
        "max": 50,
    },
    "battery_fan_temp": {
        "channel": "BatFanTmpStr",
        "sensor": "webbox_battery_fan_temp",
        "kind": "int",
        "min": 20,
        "max": 50,
    },
    "silent_time_float": {
        "channel": "SilentTmFlo",
        "sensor": "webbox_silent_time_float",
        "kind": "int",
        "min": 1,
        "max": 48,
    },
    "silent_time_max": {
        "channel": "SilentTmMax",
        "sensor": "webbox_silent_time_max",
        "kind": "int",
        "min": 1,
        "max": 168,
    },
    "self_consumption_inc": {
        "channel": "SlfCsmpIncEna",
        "sensor": "webbox_self_consumption_inc",
        "kind": "enum",
        "options": {"enable": "Enable", "disable": "Disable"},
    },
    "afra_enable": {
        "channel": "AfraEna",
        "sensor": "webbox_afra_enable",
        "kind": "enum",
        "options": {"enable": "Enable", "disable": "Disable"},
    },
    "run_mode": {
        "channel": "RnMod",
        "sensor": "webbox_run_mode",
        "kind": "text",
        "readonly": True,
    },
    "external_source": {
        "channel": "ExtSrc",
        "sensor": "webbox_external_source",
        "kind": "text",
        "readonly": True,
    },
    "cluster_config": {
        "channel": "ClstCfg",
        "sensor": "webbox_cluster_config",
        "kind": "text",
        "readonly": True,
    },
    "inverter_voltage_nom": {
        "channel": "InvVtgNom",
        "sensor": "webbox_inverter_voltage_nom",
        "kind": "int",
        "min": 80,
        "max": 150,
    },
    "inverter_frequency_nom": {
        "channel": "InvFrqNom",
        "sensor": "webbox_inverter_frequency_nom",
        "kind": "float",
        "min": 50,
        "max": 70,
        "decimals": 1,
    },
    "power_limit": {
        "channel": "Plimit",
        "sensor": "webbox_power_limit",
        "kind": "float",
        "min": 0,
        "max": 100,
        "decimals": 1,
    },
    "grid_frequency_nom": {
        "channel": "GdFrqNom",
        "sensor": "webbox_grid_frequency_nom",
        "kind": "float",
        "min": 50,
        "max": 70,
        "decimals": 1,
    },
    "grid_frequency_min": {
        "channel": "GdFrqMin",
        "sensor": "webbox_grid_frequency_min",
        "kind": "float",
        "min": 50,
        "max": 62,
        "decimals": 1,
    },
    "grid_frequency_max": {
        "channel": "GdFrqMax",
        "sensor": "webbox_grid_frequency_max",
        "kind": "float",
        "min": 57.3,
        "max": 70,
        "decimals": 1,
    },
    "grid_power_enable": {
        "channel": "GdPwrEna",
        "sensor": "webbox_grid_power_enable",
        "kind": "enum",
        "options": {"enable": "Enable", "disable": "Disable"},
    },
    "grid_soc_enable": {
        "channel": "GdSocEna",
        "sensor": "webbox_grid_soc_enable",
        "kind": "enum",
        "options": {"enable": "Enable", "disable": "Disable"},
    },
    "generator_auto": {
        "channel": "GnAutoEna",
        "sensor": "webbox_generator_auto",
        "kind": "enum",
        "options": {"on": "On", "off": "Off", "enable": "On", "disable": "Off"},
    },
    "generator_current_nom": {
        "channel": "GnCurNom",
        "sensor": "webbox_generator_current_nom",
        "kind": "int",
        "min": 0,
        "max": 1000,
    },
    "generator_power_start": {
        "channel": "GnPwrStr",
        "sensor": "webbox_generator_power_start",
        "kind": "float",
        "min": 5,
        "max": 20,
        "decimals": 1,
    },
    "generator_power_stop": {
        "channel": "GnPwrStp",
        "sensor": "webbox_generator_power_stop",
        "kind": "float",
        "min": 5,
        "max": 20,
        "decimals": 1,
    },
    "generator_voltage_min": {
        "channel": "GnVtgMin",
        "sensor": "webbox_generator_voltage_min",
        "kind": "int",
        "min": 80,
        "max": 132,
    },
    "generator_voltage_max": {
        "channel": "GnVtgMax",
        "sensor": "webbox_generator_voltage_max",
        "kind": "int",
        "min": 105,
        "max": 150,
    },
}

RPC_CHARGE_VOLTAGE_MAP: dict[str, str] = {
    spec["channel"]: spec["sensor"]
    for key, spec in RPC_PARAM_SPECS.items()
    if key.startswith("charge_voltage_")
}
CHARGE_VOLTAGE_WRITE = {
    key: spec
    for key, spec in RPC_PARAM_SPECS.items()
    if key.startswith("charge_voltage_")
}
RPC_CHANNEL_TO_SENSOR: dict[str, str] = {
    spec["channel"]: spec["sensor"] for spec in RPC_PARAM_SPECS.values()
}

RPC_PARAM_ALIASES: dict[str, str] = {
    "full": "charge_voltage_full",
    "absorption": "charge_voltage_full",
    "abs": "charge_voltage_full",
    "chrgvtgful": "charge_voltage_full",
    "float": "charge_voltage_float",
    "flo": "charge_voltage_float",
    "chrgvtgflo": "charge_voltage_float",
    "boost": "charge_voltage_boost",
    "chrgvtgboost": "charge_voltage_boost",
    "equalize": "charge_voltage_equalize",
    "equalisation": "charge_voltage_equalize",
    "equ": "charge_voltage_equalize",
    "chrgvtgequ": "charge_voltage_equalize",
    "manual": "charge_voltage_manual",
    "batchrgvtgman": "charge_voltage_manual",
    "pack": "charge_voltage_manual",
    "batchrgcurmax": "charge_current_max",
    "invchrgcurmax": "inverter_charge_current_max",
    "chrgctlop": "charge_control",
    "autoequchrgena": "auto_equalize",
    "apttmboost": "absorption_time_boost",
    "apttmequ": "absorption_time_equalize",
    "apttmful": "absorption_time_full",
    "battyp": "battery_type",
    "batvtgnom": "battery_nominal_v",
    "batcpynom": "battery_capacity_ah",
    "slfcsmpsocmin": "self_consumption_min",
    "silentena": "silent_enable",
    "sleepena": "sleep_enable",
    "gdcurnom": "grid_current_nom",
    "gdvtgmin": "grid_voltage_min",
    "gdvtgmax": "grid_voltage_max",
    "gdmod": "grid_mode",
    "fedinmod": "feed_in_mode",
    "fedinsocstr": "feed_in_soc_start",
    "fedinsocstp": "feed_in_soc_stop",
    "fedincurat": "feed_in_current",
    "cyctmequ": "cycle_time_equalize",
    "cyctmful": "cycle_time_full",
    "battmpmax": "battery_temp_max",
    "batfantmpstr": "battery_fan_temp",
    "silenttmflo": "silent_time_float",
    "silenttmmax": "silent_time_max",
    "slfcsmpsincena": "self_consumption_inc",
    "slfcsmpincena": "self_consumption_inc",
    "afraena": "afra_enable",
    "rnmod": "run_mode",
    "extsrc": "external_source",
    "clstcfg": "cluster_config",
    "invvtgnom": "inverter_voltage_nom",
    "invfrqnom": "inverter_frequency_nom",
    "plimit": "power_limit",
    "gdfrqnom": "grid_frequency_nom",
    "gdfrqmin": "grid_frequency_min",
    "gdfrqmax": "grid_frequency_max",
    "gdpwrena": "grid_power_enable",
    "gdsocena": "grid_soc_enable",
    "gnautoena": "generator_auto",
    "gncurnom": "generator_current_nom",
    "gnpwrstr": "generator_power_start",
    "gnpwrstp": "generator_power_stop",
    "gnvtgmin": "generator_voltage_min",
    "gnvtgmax": "generator_voltage_max",
}

PARAMETER_READ_CHANNELS: list[str] = [
    GRID_MAN_STR_CHANNEL,
    *RPC_CHANNEL_TO_SENSOR.keys(),
]


def resolve_rpc_param(param: str) -> str:
    key = (param or "").strip().lower().replace(" ", "_").replace("-", "_")
    key = RPC_PARAM_ALIASES.get(key, key)
    if key not in RPC_PARAM_SPECS:
        raise ValueError(
            f"Unknown WebBox parameter {param!r}; "
            f"use one of {sorted(RPC_PARAM_SPECS)}"
        )
    return key


def resolve_charge_voltage_param(param: str) -> str:
    key = resolve_rpc_param(param)
    if key not in CHARGE_VOLTAGE_WRITE:
        raise ValueError(
            f"Unknown charge voltage parameter {param!r}; "
            f"use one of {sorted(CHARGE_VOLTAGE_WRITE)}"
        )
    return key


def _parse_param_number(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw in ("---", "-", "-----"):
        return None
    try:
        return float(raw.split()[0].replace(",", "."))
    except ValueError:
        return None


def webbox_password_hash(password: str) -> str:
    """MD5 hash of the WebBox access-level password, per the RPC spec."""
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def parse_overview_ajax(payload: dict) -> dict:
    """Parse the ``home.ajax`` response into {sensor_key: float}."""
    result: dict[str, float] = {}
    for item in payload.get("Items", []):
        for name, raw_value in item.items():
            key = OVERVIEW_KEY_MAP.get(name)
            if key is None:
                continue
            token = str(raw_value).strip().split(" ", 1)[0]
            try:
                result[key] = float(token)
            except ValueError:
                _LOGGER.debug(
                    "[tesla_evtv_bms] Unparseable WebBox value for %s: %r",
                    name,
                    raw_value,
                )
    return result


def build_rpc_request(
    proc: str,
    *,
    password: str | None = None,
    params: dict | None = None,
    request_id: str = "1",
) -> dict:
    request: dict[str, Any] = {
        "version": RPC_VERSION,
        "proc": proc,
        "id": request_id,
        "format": "JSON",
    }
    if password:
        request["passwd"] = webbox_password_hash(password)
    if params:
        request["params"] = params
    return request


def _parse_rpc_envelope(body: str) -> dict | None:
    """Parse RPC JSON; return None if HTML frameset / non-JSON."""
    text = (body or "").strip()
    if not text or text.startswith("<") or not text.startswith("{"):
        return None
    try:
        envelope = json.loads(text)
    except ValueError:
        return None
    if not isinstance(envelope, dict):
        return None
    return envelope


def parse_rpc_plant_overview(body: str) -> dict | None:
    """Parse GetPlantOverview into our sensor keys."""
    envelope = _parse_rpc_envelope(body)
    if not envelope:
        return None
    result = envelope.get("result")
    if not isinstance(result, dict):
        return None

    out: dict[str, Any] = {}
    for channel in result.get("overview", []):
        if not isinstance(channel, dict):
            continue
        meta = str(channel.get("meta") or channel.get("name") or "")
        value = channel.get("value")
        if value is None:
            continue
        key = RPC_OVERVIEW_MAP.get(meta) or RPC_OVERVIEW_MAP.get(
            meta.replace(" ", "")
        )
        if key is None:
            # Keep raw under webbox_rpc_* for diagnostics
            try:
                out[f"webbox_rpc_{meta.lower()}"] = float(value)
            except (TypeError, ValueError):
                pass
            continue
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out or None


def parse_rpc_devices(body: str) -> list[str]:
    """Return device keys from GetDevices."""
    envelope = _parse_rpc_envelope(body)
    if not envelope:
        return []
    result = envelope.get("result")
    if not isinstance(result, dict):
        return []
    keys: list[str] = []
    for dev in result.get("devices") or []:
        if isinstance(dev, dict) and dev.get("key"):
            keys.append(str(dev["key"]))
    return keys


def parse_rpc_process_data(body: str) -> dict[str, Any]:
    """Map GetProcessData channels onto our webbox_* keys."""
    envelope = _parse_rpc_envelope(body)
    if not envelope:
        return {}
    result = envelope.get("result")
    if not isinstance(result, dict):
        return {}

    out: dict[str, Any] = {}
    for device in result.get("devices") or []:
        if not isinstance(device, dict):
            continue
        for channel in device.get("channels") or []:
            if not isinstance(channel, dict):
                continue
            meta = str(channel.get("meta") or channel.get("name") or "")
            value = channel.get("value")
            if value is None or meta not in RPC_PROCESS_MAP:
                continue
            key, kind = RPC_PROCESS_MAP[meta]
            if key in out:
                continue  # first channel wins
            if kind == "text":
                out[key] = str(value)
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            if kind == "float_kw":
                num = num * 1000.0  # kW → W for our POWER sensors
            out[key] = num
    return out


def normalize_grid_man_str(value: str | None) -> str | None:
    """Normalize a GdManStr value or mode alias to Start|Auto|Stop."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw in ("---", "-", "-----"):
        return None
    # Exact RPC option
    for opt in GRID_MAN_STR_VALUES:
        if raw == opt or raw.lower() == opt.lower():
            return opt
    key = raw.lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "start": "Start",
        "manual_on": "Start",
        "manual": "Start",
        "on": "Start",
        "request": "Start",
        "grid": "Start",
        "auto": "Auto",
        "automatic": "Auto",
        "stop": "Stop",
        "off": "Stop",
    }
    return aliases.get(key)


def apply_grid_man_str(values: dict[str, Any], raw: str | None) -> None:
    """Fill webbox_grid_control* from a GdManStr RPC value."""
    man = normalize_grid_man_str(raw)
    if man is None:
        return
    opt = GRID_MAN_STR_TO_OPTION[man]
    values["webbox_grid_man_str"] = man
    values["webbox_grid_control_option"] = opt
    values["webbox_grid_control"] = GRID_MAN_STR_LABELS[man]
    values["webbox_grid_control_code"] = GRID_MAN_STR_TO_CODE[man]


def parse_rpc_parameters(body: str) -> dict[str, Any]:
    """Map GetParameter / SetParameter channels (e.g. GdManStr) to sensors."""
    envelope = _parse_rpc_envelope(body)
    if not envelope or "error" in envelope:
        return {}
    result = envelope.get("result")
    if not isinstance(result, dict):
        return {}

    out: dict[str, Any] = {}
    for device in result.get("devices") or []:
        if not isinstance(device, dict):
            continue
        for channel in device.get("channels") or []:
            if not isinstance(channel, dict):
                continue
            meta = str(channel.get("meta") or channel.get("name") or "")
            value = channel.get("value")
            if value is None:
                continue
            if meta == GRID_MAN_STR_CHANNEL:
                apply_grid_man_str(out, str(value))
                continue
            sensor_key = RPC_CHANNEL_TO_SENSOR.get(meta)
            if not sensor_key:
                continue
            spec = next(
                (s for s in RPC_PARAM_SPECS.values() if s["sensor"] == sensor_key),
                {"kind": "float"},
            )
            kind = spec.get("kind") or "float"
            if kind in ("float", "int"):
                num = _parse_param_number(value)
                if num is None:
                    continue
                out[sensor_key] = int(round(num)) if kind == "int" else num
            else:
                raw = str(value).strip()
                if raw and raw not in ("---", "-", "-----"):
                    out[sensor_key] = raw
    return out


def mode_to_grid_man_str(mode: str) -> str:
    """Resolve set_grid_control mode → GdManStr value (Start|Auto|Stop)."""
    man = normalize_grid_man_str(mode)
    if man is None:
        raise ValueError(
            f"Unknown grid control mode {mode!r}; "
            f"use off | manual_on | automatic (or Start | Auto | Stop)"
        )
    return man


def _rpc_error_tag(err: BaseException) -> str:
    """aiohttp Connect errors are often empty (`error:`); keep a usable tag."""
    msg = str(err).strip()
    name = type(err).__name__
    if not msg:
        return f"error:{name}"
    if msg.startswith(name):
        return f"error:{msg}"
    return f"error:{name}: {msg}"


def _is_connect_failure(status: str) -> bool:
    s = (status or "").lower()
    return any(
        t in s
        for t in (
            "connect call failed",
            "cannot connect",
            "clientconnectorerror",
            "connection refused",
            "network is unreachable",
            "no route to host",
            "name or service not known",
        )
    )


def _rpc_timeout(total: float):
    """Fail fast on a down WebBox so ajax/Modbus can still run."""
    if ClientTimeout is None:
        return total
    connect = min(3.0, max(1.0, float(total) / 4.0))
    try:
        return ClientTimeout(total=float(total), sock_connect=connect, connect=connect)
    except TypeError:
        return float(total)


# host -> circuit (skip RPC after connect failures; rate-limit warnings)
_RPC_GATE: dict[str, dict[str, Any]] = {}
_WARN_INTERVAL_S = 300.0


def _rpc_gate(host: str) -> dict[str, Any]:
    gate = _RPC_GATE.get(host)
    if gate is None:
        gate = {
            "until": 0.0,
            "consecutive": 0,
            "last_warn": 0.0,
            "last_logged": "",
        }
        _RPC_GATE[host] = gate
    return gate


async def _rpc_call(
    session,
    host: str,
    proc: str,
    *,
    password: str | None,
    params: dict | None = None,
    timeout: float = 12,
    retries: int = 3,
) -> tuple[str | None, str]:
    """POST form-encoded RPC. Returns (body_text or None, status tag).

    WebBox firmware is fragile under keep-alive + concurrent polls (connection
    reset / disconnect). Force Connection: close and retry transient failures.
    Hard connect failures (host down) are not retried — they just delay ajax.
    """
    payload = build_rpc_request(proc, password=password, params=params)
    # Critical: WebBox expects form field name "RPC", not raw JSON body.
    form = urlencode({"RPC": json.dumps(payload, separators=(",", ":"))})
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Connection": "close",
    }
    last_status = "error:unknown"
    aio_timeout = _rpc_timeout(timeout)
    for attempt in range(max(1, retries)):
        try:
            async with session.post(
                f"http://{host}/rpc",
                data=form,
                headers=headers,
                timeout=aio_timeout,
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    last_status = f"http_{resp.status}"
                    # 5xx may be transient on overloaded WebBox
                    if resp.status >= 500 and attempt + 1 < retries:
                        await asyncio.sleep(0.35 * (attempt + 1))
                        continue
                    return None, last_status
        except Exception as err:  # noqa: BLE001
            last_status = _rpc_error_tag(err)
            err_l = last_status.lower()
            # Host unreachable — retrying 3×12s piles polls and wedges the box.
            if _is_connect_failure(last_status):
                return None, last_status
            transient = any(
                t in err_l
                for t in (
                    "reset",
                    "disconnect",
                    "timeout",
                    "broken pipe",
                    "eof",
                    "server disconnected",
                )
            )
            if transient and attempt + 1 < retries:
                await asyncio.sleep(0.35 * (attempt + 1))
                continue
            return None, last_status

        if not body or body.lstrip().startswith("<"):
            return None, "disabled_or_html"
        if not body.lstrip().startswith("{"):
            return None, "non_json"
        return body, "ok"

    return None, last_status


def _log_rpc_unusable(host: str, status: str, *, ajax_ok: bool) -> None:
    """Warn once, then at most every 5 minutes unless the status string changes."""
    gate = _rpc_gate(host)
    now = time.monotonic()
    if (
        gate["consecutive"] <= 1
        or status != gate.get("last_logged")
        or (now - float(gate["last_warn"])) >= _WARN_INTERVAL_S
    ):
        gate["last_warn"] = now
        gate["last_logged"] = status
        level = logging.INFO if ajax_ok else logging.WARNING
        _LOGGER.log(
            level,
            "[tesla_evtv_bms] WebBox RPC not usable on %s (%s); using home.ajax. "
            "Ensure RPC is enabled and password is correct (plain text; MD5 is applied automatically).",
            host,
            status,
        )
    else:
        _LOGGER.debug(
            "[tesla_evtv_bms] WebBox RPC still unusable on %s (%s) x%s",
            host,
            status,
            gate["consecutive"],
        )


async def async_poll_webbox(session, host: str, password: str | None) -> dict:
    """Fetch WebBox values via RPC (preferred) with home.ajax fallback."""
    values: dict[str, Any] = {}
    rpc_ok = False
    host = (host or "").strip()
    gate = _rpc_gate(host)
    now = time.monotonic()
    skip_rpc = bool(host) and now < float(gate.get("until") or 0)

    # 1) Plant overview via RPC (skipped while the connect circuit is open)
    if skip_rpc:
        status = str(gate.get("last_logged") or "backoff")
        values["webbox_rpc_status"] = status
        body = None
    else:
        body, status = await _rpc_call(
            session, host, "GetPlantOverview", password=password
        )
    if body:
        overview = parse_rpc_plant_overview(body)
        if overview:
            values.update(overview)
            rpc_ok = True
            values["webbox_rpc_status"] = "ok"
    else:
        values["webbox_rpc_status"] = status
        if not skip_rpc:
            gate["consecutive"] = int(gate.get("consecutive") or 0) + 1
            if _is_connect_failure(status):
                delay = min(300.0, 30.0 * (2 ** min(int(gate["consecutive"]) - 1, 3)))
                gate["until"] = time.monotonic() + delay

    # 2) SI process data + grid-start parameter via RPC
    if rpc_ok or status == "ok":
        dev_body, _ = await _rpc_call(
            session, host, "GetDevices", password=password
        )
        devices = parse_rpc_devices(dev_body or "")
        # Prefer Sunny Island keys
        si_keys = [k for k in devices if k.upper().startswith("SI")]
        targets = si_keys or devices
        if targets:
            device_key = targets[0]
            values["webbox_device_key"] = device_key
            pd_body, _ = await _rpc_call(
                session,
                host,
                "GetProcessData",
                password=password,
                params={"devices": [{"key": device_key, "channels": None}]},
                timeout=20,
            )
            if pd_body:
                proc = parse_rpc_process_data(pd_body)
                # SI process data enriches sensors; never clobber plant overview power/yields
                protect = {
                    "webbox_power",
                    "webbox_daily_yield",
                    "webbox_total_yield",
                    "webbox_power_kw",
                }
                for k, v in proc.items():
                    if k in protect and k in values:
                        continue
                    values[k] = v
                rpc_ok = True
                values["webbox_rpc_status"] = "ok"

            # 2b) Grid start parameter (GdManStr) — real control on SI6048 WebBox.
            # GetParameter requires channels as plain string names (not {meta:…}
            # objects — those return "Error building response" on SI6048UM).
            gp_body, _ = await _rpc_call(
                session,
                host,
                "GetParameter",
                password=password,
                params={
                    "devices": [
                        {
                            "key": device_key,
                            "channels": list(PARAMETER_READ_CHANNELS),
                        }
                    ]
                },
                timeout=15,
            )
            if gp_body:
                params = parse_rpc_parameters(gp_body)
                if params:
                    values.update(params)
                    rpc_ok = True
                    values["webbox_rpc_status"] = "ok"

    # 3) home.ajax fallback for core power/yield if still missing
    try:
        async with session.get(f"http://{host}/home.ajax", timeout=8) as resp:
            resp.raise_for_status()
            ajax = parse_overview_ajax(await resp.json(content_type=None))
            for k, v in ajax.items():
                values.setdefault(k, v)
            if not rpc_ok:
                values.setdefault("webbox_rpc_status", "ajax_only")
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("[tesla_evtv_bms] home.ajax failed: %s", err)
        if not values:
            raise

    if rpc_ok:
        if gate.get("consecutive"):
            _LOGGER.info(
                "[tesla_evtv_bms] WebBox RPC recovered on %s after %s failures",
                host,
                gate["consecutive"],
            )
        gate["consecutive"] = 0
        gate["until"] = 0.0
        _LOGGER.debug(
            "[tesla_evtv_bms] WebBox RPC ok host=%s keys=%s",
            host,
            sorted(values.keys())[:12],
        )
    else:
        _log_rpc_unusable(
            host,
            str(values.get("webbox_rpc_status") or status or "error"),
            ajax_ok="webbox_power" in values,
        )

    return values


async def async_write_grid_control_rpc(
    session,
    host: str,
    mode: str,
    *,
    password: str | None = None,
    device_key: str | None = None,
) -> bool:
    """Write SI GdManStr via WebBox SetParameter (Start / Auto / Stop).

    This is the working path on SI6048UM + Sunny WebBox. Modbus register
    40527 often returns illegal-address on the same hardware.
    """
    man = mode_to_grid_man_str(mode)
    host = (host or "").strip()
    if not host:
        raise ValueError("WebBox host is empty")

    key = (device_key or "").strip() or None
    if not key:
        dev_body, status = await _rpc_call(
            session, host, "GetDevices", password=password
        )
        devices = parse_rpc_devices(dev_body or "")
        si_keys = [k for k in devices if k.upper().startswith("SI")]
        targets = si_keys or devices
        if not targets:
            _LOGGER.warning(
                "WebBox grid control RPC: no devices on %s (%s)", host, status
            )
            return False
        key = targets[0]

    body, status = await _rpc_call(
        session,
        host,
        "SetParameter",
        password=password,
        params={
            "devices": [
                {
                    "key": key,
                    "channels": [{"meta": GRID_MAN_STR_CHANNEL, "value": man}],
                }
            ]
        },
        timeout=20,
    )
    if not body:
        _LOGGER.warning(
            "WebBox grid control RPC write failed mode=%s host=%s status=%s",
            man,
            host,
            status,
        )
        return False

    envelope = _parse_rpc_envelope(body)
    if not envelope or "error" in envelope:
        err = (envelope or {}).get("error") if isinstance(envelope, dict) else None
        _LOGGER.warning(
            "WebBox grid control RPC error mode=%s host=%s err=%s body=%s",
            man,
            host,
            err,
            (body or "")[:200],
        )
        return False

    # Confirm echoed value when present
    parsed = parse_rpc_parameters(body)
    echoed = parsed.get("webbox_grid_man_str")
    if echoed and echoed != man:
        _LOGGER.warning(
            "WebBox grid control RPC wrote %s but device returned %s on %s",
            man,
            echoed,
            host,
        )
        return False

    _LOGGER.info(
        "WebBox grid control RPC → GdManStr=%s on %s device=%s",
        man,
        host,
        key,
    )
    return True


# Keys sourced from GetParameter / SetParameter — prefer over Modbus when present.
RPC_PARAMETER_KEYS = frozenset(
    {
        "webbox_grid_man_str",
        "webbox_grid_control_option",
        "webbox_grid_control",
        "webbox_grid_control_code",
        *RPC_CHANNEL_TO_SENSOR.values(),
    }
)


def merge_modbus_without_clobbering_rpc_params(
    http_values: dict[str, Any], mb_values: dict[str, Any]
) -> dict[str, Any]:
    """Merge Modbus onto HTTP/RPC; keep RPC parameter-sourced grid control."""
    out = dict(http_values)
    protect = bool(out.get("webbox_grid_man_str") or out.get("webbox_grid_control_option"))
    rpc_sensors = set(RPC_CHANNEL_TO_SENSOR.values())
    for key, val in mb_values.items():
        if protect and key in RPC_PARAMETER_KEYS:
            continue
        if key in rpc_sensors and key in out:
            continue
        out[key] = val
    return out


def apply_grid_control_optimistic(values: dict[str, Any], mode: str) -> str:
    """Update runtime values after a successful write; returns mode id."""
    man = mode_to_grid_man_str(mode)
    apply_grid_man_str(values, man)
    return GRID_MAN_STR_TO_OPTION[man]


def apply_rpc_param_optimistic(values: dict[str, Any], param: str, stored: Any) -> None:
    spec = RPC_PARAM_SPECS[resolve_rpc_param(param)]
    values[spec["sensor"]] = stored


def apply_charge_voltage_optimistic(
    values: dict[str, Any], param: str, number: float
) -> None:
    apply_rpc_param_optimistic(values, param, number)


def _render_rpc_value(spec: dict[str, Any], value: Any) -> tuple[str, Any]:
    """Return (string sent to WebBox, value stored on sensors)."""
    kind = spec.get("kind") or "float"
    if kind == "enum":
        options: dict[str, str] = spec.get("options") or {}
        raw = str(value).strip()
        key = raw.lower().replace(" ", "_").replace("-", "_")
        if key in options:
            rendered = options[key]
        elif raw in options.values():
            rendered = raw
        else:
            raise ValueError(
                f"Invalid value {value!r}; options={sorted(options)}"
            )
        return rendered, rendered
    if kind == "text":
        raw = str(value).strip()
        if not raw:
            raise ValueError("empty value")
        return raw, raw
    number = _parse_param_number(value)
    if number is None:
        raise ValueError(f"Invalid number {value!r}")
    lo = spec.get("min")
    hi = spec.get("max")
    if lo is not None and number < float(lo):
        raise ValueError(f"value must be ≥ {lo}")
    if hi is not None and number > float(hi):
        raise ValueError(f"value must be ≤ {hi}")
    if kind == "int":
        stored = int(round(number))
        return str(stored), stored
    decimals = int(spec.get("decimals") or 2)
    stored = round(number, decimals)
    return f"{stored:.{decimals}f}", stored


async def async_write_rpc_parameter(
    session,
    host: str,
    param: str,
    value: Any,
    *,
    password: str | None = None,
    device_key: str | None = None,
) -> tuple[bool, Any]:
    """Write a WebBox GetParameter/SetParameter channel. Returns (ok, stored)."""
    param_key = resolve_rpc_param(param)
    spec = RPC_PARAM_SPECS[param_key]
    if spec.get("readonly"):
        raise ValueError(f"{param_key} is read-only")
    rendered, stored = _render_rpc_value(spec, value)

    host = (host or "").strip()
    if not host:
        raise ValueError("WebBox host is empty")

    key = (device_key or "").strip() or None
    if not key:
        dev_body, status = await _rpc_call(
            session, host, "GetDevices", password=password
        )
        devices = parse_rpc_devices(dev_body or "")
        si_keys = [k for k in devices if k.upper().startswith("SI")]
        targets = si_keys or devices
        if not targets:
            _LOGGER.warning(
                "WebBox parameter RPC: no devices on %s (%s)", host, status
            )
            return False, stored
        key = targets[0]

    channel = spec["channel"]
    body, status = await _rpc_call(
        session,
        host,
        "SetParameter",
        password=password,
        params={
            "devices": [
                {
                    "key": key,
                    "channels": [{"meta": channel, "value": rendered}],
                }
            ]
        },
        timeout=20,
    )
    if not body:
        _LOGGER.warning(
            "WebBox parameter RPC write failed %s=%s host=%s status=%s",
            channel,
            rendered,
            host,
            status,
        )
        return False, stored

    envelope = _parse_rpc_envelope(body)
    if not envelope or "error" in envelope:
        err = (envelope or {}).get("error") if isinstance(envelope, dict) else None
        _LOGGER.warning(
            "WebBox parameter RPC error %s=%s host=%s err=%s",
            channel,
            rendered,
            host,
            err,
        )
        return False, stored

    _LOGGER.info(
        "WebBox parameter RPC → %s=%s on %s device=%s",
        channel,
        rendered,
        host,
        key,
    )
    return True, stored


async def async_write_charge_voltage_rpc(
    session,
    host: str,
    param: str,
    value: Any,
    *,
    password: str | None = None,
    device_key: str | None = None,
) -> tuple[bool, Any]:
    return await async_write_rpc_parameter(
        session,
        host,
        param,
        value,
        password=password,
        device_key=device_key,
    )


async def async_set_grid_control(
    session,
    host: str,
    mode: str,
    *,
    password: str | None = None,
    device_key: str | None = None,
    use_modbus: bool = True,
    modbus_port: int = 502,
    unit_device: int = 3,
) -> bool:
    """Write grid control: RPC SetParameter (GdManStr) first, Modbus fallback.

    SI6048UM + Sunny WebBox typically reject holding register 40527 (illegal
    address). WebBox JSON-RPC SetParameter on channel GdManStr is the path
    that works — password is the WebBox access password (e.g. ``sma``).
    """
    host = (host or "").strip()
    if not host:
        raise ValueError("WebBox host is empty")

    # Validate mode early (raises ValueError on unknown)
    mode_to_grid_man_str(mode)

    ok = await async_write_grid_control_rpc(
        session,
        host,
        mode,
        password=password,
        device_key=device_key,
    )
    if ok:
        return True

    if not use_modbus:
        _LOGGER.warning(
            "WebBox grid control failed on %s (RPC SetParameter only; Modbus disabled)",
            host,
        )
        return False

    from .webbox_modbus import async_write_grid_control as mb_write

    _LOGGER.info(
        "WebBox grid control RPC failed on %s — trying Modbus reg 40527",
        host,
    )
    return await mb_write(
        host,
        mode,
        port=modbus_port,
        unit_device=unit_device,
    )
