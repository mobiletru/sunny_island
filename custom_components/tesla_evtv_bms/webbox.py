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
from typing import Any
from urllib.parse import urlencode

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
    "BatChrgVtg": ("webbox_bat_chrg_vtg", "float"),  # live BMS / charge target (V)
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

# SI parameter: battery type (GetParameter / SetParameter).
# Official SI 5048U firmware 7.304/7.300 channel list (menu 221.01 BatTyp,
# also QCG 003.07): --- · VRLA · FLA · NiCd · LiIon_Ext-BMS · Other.
# Tesla EVTV lithium pack with external BMS uses LiIon_Ext-BMS.
# RPC-only — no documented Modbus holding register in this repo / SMA public docs.
BAT_TYP_CHANNEL = "BatTyp"
BAT_TYP_LIION_EXT_BMS = "LiIon_Ext-BMS"
BAT_TYP_VALUES = ("VRLA", "FLA", "NiCd", "LiIon_Ext-BMS", "Other")
BAT_TYP_LABELS: dict[str, str] = {
    "VRLA": "VRLA",
    "FLA": "FLA",
    "NiCd": "NiCd",
    "LiIon_Ext-BMS": "Lithium (ext. BMS)",
    "Other": "Other",
}

# VRLA / battery voltage channels (GetParameter / SetParameter).
# Official SMA SI 5048 Technical Description SI5048-TB-TEN110340 and
# SBU 5000 parameter errata ParaSBU50-E-TB-en-11:
#   222.07–10 ChrgVtg* = cell voltage setpoints (V/cell)
#   221.03 BatVtgNom = nominal battery voltage (V; 48 / 45.6)
#   226.01 BatChrgVtgMan = manual charge voltage with BMS off (41–63 V)
#   120.03 BatChrgVtg = live charging voltage target (V, display / process)
# SI 5048U firmware 7.304/7.300 string table also lists BatVtgMax, BatVtgMin,
# BatMinDchrgVtg, BatChrgVtgSimMan — exposed with the firmware names; no
# published range found for those four. RPC-only; no Modbus registers.
#
# kind: "cell" = V/cell setpoint · "bank" = pack volts
# writable False = live / BMS-provided (GetParameter or GetProcessData only)
SI_VOLTAGE_CHANNELS: dict[str, dict[str, Any]] = {
    "ChrgVtgBoost": {
        "sensor_key": "webbox_chrg_vtg_boost",
        "param_ids": ("chrg_vtg_boost", "chrgvtgboost"),
        "writable": True,
        "kind": "cell",
        "min": 1.5,
        "max": 2.7,
        "title": "Boost charge (ChrgVtgBoost)",
    },
    "ChrgVtgFul": {
        "sensor_key": "webbox_chrg_vtg_ful",
        "param_ids": ("chrg_vtg_ful", "chrgvtgful"),
        "writable": True,
        "kind": "cell",
        "min": 1.5,
        "max": 2.7,
        "title": "Full charge (ChrgVtgFul)",
    },
    "ChrgVtgEqu": {
        "sensor_key": "webbox_chrg_vtg_equ",
        "param_ids": ("chrg_vtg_equ", "chrgvtgequ"),
        "writable": True,
        "kind": "cell",
        "min": 1.5,
        "max": 2.7,
        "title": "Equalize charge (ChrgVtgEqu)",
    },
    "ChrgVtgFlo": {
        "sensor_key": "webbox_chrg_vtg_flo",
        "param_ids": ("chrg_vtg_flo", "chrgvtgflo", "chrg_vtg_float"),
        "writable": True,
        "kind": "cell",
        "min": 1.4,
        "max": 2.4,
        "title": "Float charge (ChrgVtgFlo)",
    },
    "BatVtgNom": {
        "sensor_key": "webbox_bat_vtg_nom",
        "param_ids": ("bat_vtg_nom", "batvtgnom"),
        "writable": True,
        "kind": "bank",
        "min": 40.0,
        "max": 60.0,
        "title": "Nominal battery V (BatVtgNom)",
    },
    "BatVtgMax": {
        "sensor_key": "webbox_bat_vtg_max",
        "param_ids": ("bat_vtg_max", "batvtgmax"),
        "writable": True,
        "kind": "bank",
        "min": 1.0,
        "max": 100.0,
        "title": "Battery V max (BatVtgMax)",
    },
    "BatVtgMin": {
        "sensor_key": "webbox_bat_vtg_min",
        "param_ids": ("bat_vtg_min", "batvtgmin"),
        "writable": True,
        "kind": "bank",
        "min": 1.0,
        "max": 100.0,
        "title": "Battery V min (BatVtgMin)",
    },
    "BatMinDchrgVtg": {
        "sensor_key": "webbox_bat_min_dchrg_vtg",
        "param_ids": ("bat_min_dchrg_vtg", "batmindchrgvtg"),
        "writable": True,
        "kind": "bank",
        "min": 1.0,
        "max": 100.0,
        "title": "Min discharge V (BatMinDchrgVtg)",
    },
    "BatChrgVtgSimMan": {
        "sensor_key": "webbox_bat_chrg_vtg_sim_man",
        "param_ids": ("bat_chrg_vtg_sim_man", "batchrgvtgsimman"),
        "writable": True,
        "kind": "bank",
        "min": 41.0,
        "max": 63.0,
        "title": "Sim/manual charge V (BatChrgVtgSimMan)",
    },
    "BatChrgVtgMan": {
        "sensor_key": "webbox_bat_chrg_vtg_man",
        "param_ids": ("bat_chrg_vtg_man", "batchrgvtgman"),
        "writable": True,
        "kind": "bank",
        "min": 41.0,
        "max": 63.0,
        "title": "Manual charge V (BatChrgVtgMan)",
    },
    "BatChrgVtg": {
        "sensor_key": "webbox_bat_chrg_vtg",
        "param_ids": ("bat_chrg_vtg", "batchrgvtg"),
        "writable": False,
        "kind": "bank",
        "title": "Live charge V (BatChrgVtg)",
    },
}

GET_PARAMETER_CORE_CHANNELS: tuple[str, ...] = (
    GRID_MAN_STR_CHANNEL,
    BAT_TYP_CHANNEL,
)
GET_PARAMETER_VOLTAGE_CHANNELS: tuple[str, ...] = tuple(SI_VOLTAGE_CHANNELS)
GET_PARAMETER_CHANNELS: tuple[str, ...] = (
    GET_PARAMETER_CORE_CHANNELS + GET_PARAMETER_VOLTAGE_CHANNELS
)
SI_VOLTAGE_SENSOR_KEYS: tuple[str, ...] = tuple(
    spec["sensor_key"] for spec in SI_VOLTAGE_CHANNELS.values()
)


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


def normalize_bat_typ(value: str | None) -> str | None:
    """Normalize a BatTyp value or alias to an official firmware option.

    Official strings (SI 5048U 7.304/7.300): VRLA, FLA, NiCd, LiIon_Ext-BMS, Other.
    ``---`` / empty is treated as unset. Tesla EVTV aliases map to LiIon_Ext-BMS.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw in ("---", "-", "-----"):
        return None
    for opt in BAT_TYP_VALUES:
        if raw == opt or raw.lower() == opt.lower():
            return opt
    key = raw.lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "liion_ext_bms": BAT_TYP_LIION_EXT_BMS,
        "liion_extbms": BAT_TYP_LIION_EXT_BMS,
        "liion": BAT_TYP_LIION_EXT_BMS,
        "lithium": BAT_TYP_LIION_EXT_BMS,
        "lithium_ext_bms": BAT_TYP_LIION_EXT_BMS,
        "tesla": BAT_TYP_LIION_EXT_BMS,
        "evtv": BAT_TYP_LIION_EXT_BMS,
        "tesla_evtv": BAT_TYP_LIION_EXT_BMS,
        "vrla": "VRLA",
        "fla": "FLA",
        "nicd": "NiCd",
        "ni_cd": "NiCd",
        "other": "Other",
    }
    return aliases.get(key)


def apply_bat_typ(values: dict[str, Any], raw: str | None) -> None:
    """Fill webbox_bat_typ from a BatTyp RPC value."""
    typ = normalize_bat_typ(raw)
    if typ is None:
        return
    values["webbox_bat_typ"] = typ


def apply_bat_typ_optimistic(values: dict[str, Any], value: str) -> str:
    """Update runtime values after a successful BatTyp write; returns official string."""
    typ = value_to_bat_typ(value)
    apply_bat_typ(values, typ)
    return typ


def parse_voltage_value(raw: Any) -> float | None:
    """Parse a WebBox voltage token (``2.40``, ``2.40 V``, ``54.0 V``)."""
    if raw is None:
        return None
    text = str(raw).strip().replace(",", ".")
    if not text or text in ("---", "-", "-----"):
        return None
    token = text.split()[0]
    try:
        return float(token)
    except ValueError:
        return None


def format_voltage_rpc_value(num: float) -> str:
    """Compact decimal string for SetParameter (2.40 → 2.4, 54.0 → 54)."""
    text = f"{float(num):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def resolve_si_voltage_param(param: str) -> dict[str, Any] | None:
    """Resolve set_si_parameter id / firmware name → voltage channel spec."""
    raw = str(param or "").strip()
    if not raw:
        return None
    if raw in SI_VOLTAGE_CHANNELS:
        return {"channel": raw, **SI_VOLTAGE_CHANNELS[raw]}
    key = raw.lower().replace(" ", "_").replace("-", "_")
    for channel, spec in SI_VOLTAGE_CHANNELS.items():
        aliases = {
            channel.lower().replace("-", "_"),
            spec["sensor_key"].removeprefix("webbox_"),
            *(a.lower().replace("-", "_") for a in spec.get("param_ids") or ()),
        }
        if key in aliases:
            return {"channel": channel, **spec}
    return None


def value_to_voltage(param: str, value: Any) -> tuple[dict[str, Any], float]:
    """Resolve + validate a voltage write. Returns (spec, number)."""
    spec = resolve_si_voltage_param(param)
    if spec is None:
        raise ValueError(f"Unknown SI voltage parameter {param!r}")
    if not spec.get("writable", True):
        raise ValueError(
            f"{spec['channel']} is read-only (live / BMS-provided charge voltage)"
        )
    num = parse_voltage_value(value)
    if num is None:
        raise ValueError(f"Invalid voltage {value!r} for {spec['channel']}")
    lo = spec.get("min")
    hi = spec.get("max")
    if lo is not None and num < float(lo):
        raise ValueError(f"{spec['channel']} must be ≥ {lo}")
    if hi is not None and num > float(hi):
        raise ValueError(f"{spec['channel']} must be ≤ {hi}")
    return spec, num


def apply_voltage(values: dict[str, Any], channel: str, raw: Any) -> None:
    """Fill a webbox_* voltage sensor from a GetParameter / SetParameter value."""
    spec = SI_VOLTAGE_CHANNELS.get(channel)
    if not spec:
        return
    num = parse_voltage_value(raw)
    if num is None:
        return
    values[spec["sensor_key"]] = num


def apply_voltage_optimistic(values: dict[str, Any], param: str, value: Any) -> float:
    """Update runtime values after a successful voltage write."""
    spec, num = value_to_voltage(param, value)
    values[spec["sensor_key"]] = num
    return num


def value_to_bat_typ(value: str) -> str:
    """Resolve set_si_parameter bat_typ value → official BatTyp string."""
    typ = normalize_bat_typ(value)
    if typ is None:
        raise ValueError(
            f"Unknown BatTyp {value!r}; "
            f"use one of {', '.join(BAT_TYP_VALUES)} "
            f"(Tesla EVTV: {BAT_TYP_LIION_EXT_BMS})"
        )
    return typ


def parse_rpc_parameters(body: str) -> dict[str, Any]:
    """Map GetParameter / SetParameter channels to sensors."""
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
            elif meta == BAT_TYP_CHANNEL:
                apply_bat_typ(out, str(value))
            elif meta in SI_VOLTAGE_CHANNELS:
                apply_voltage(out, meta, value)
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
    """
    payload = build_rpc_request(proc, password=password, params=params)
    # Critical: WebBox expects form field name "RPC", not raw JSON body.
    form = urlencode({"RPC": json.dumps(payload, separators=(",", ":"))})
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Connection": "close",
    }
    last_status = "error:unknown"
    for attempt in range(max(1, retries)):
        try:
            async with session.post(
                f"http://{host}/rpc",
                data=form,
                headers=headers,
                timeout=timeout,
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
            last_status = f"error:{err}"
            err_l = str(err).lower()
            transient = any(
                t in err_l
                for t in (
                    "reset",
                    "disconnect",
                    "timeout",
                    "connect",
                    "broken pipe",
                    "eof",
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


async def async_poll_webbox(session, host: str, password: str | None) -> dict:
    """Fetch WebBox values via RPC (preferred) with home.ajax fallback."""
    values: dict[str, Any] = {}
    rpc_ok = False

    # 1) Plant overview via RPC
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

            # 2b) SI parameters — official WebBox RPC channels.
            # GetParameter requires channels as plain string names (not {meta:…}
            # objects — those return "Error building response" on SI6048UM).
            # Combined list first; if WebBox rejects an unknown voltage channel,
            # fall back to GdManStr+BatTyp, then GdManStr alone, then voltages
            # as their own request so grid/BatTyp keep working.
            params = await _rpc_get_parameters(
                session, host, password, device_key, GET_PARAMETER_CHANNELS
            )
            if not (
                params.get("webbox_grid_man_str") or params.get("webbox_bat_typ")
            ):
                core = await _rpc_get_parameters(
                    session,
                    host,
                    password,
                    device_key,
                    GET_PARAMETER_CORE_CHANNELS,
                )
                if core:
                    params = {**params, **core}
                if not (
                    params.get("webbox_grid_man_str") or params.get("webbox_bat_typ")
                ):
                    gd = await _rpc_get_parameters(
                        session,
                        host,
                        password,
                        device_key,
                        (GRID_MAN_STR_CHANNEL,),
                    )
                    params.update(gd)
                if not any(k in params for k in SI_VOLTAGE_SENSOR_KEYS):
                    extra = await _rpc_get_parameters(
                        session,
                        host,
                        password,
                        device_key,
                        GET_PARAMETER_VOLTAGE_CHANNELS,
                    )
                    params.update(extra)
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
        _LOGGER.debug(
            "[tesla_evtv_bms] WebBox RPC ok host=%s keys=%s",
            host,
            sorted(values.keys())[:12],
        )
    else:
        _LOGGER.warning(
            "[tesla_evtv_bms] WebBox RPC not usable on %s (%s); using home.ajax. "
            "Ensure RPC is enabled and password is correct (plain text; MD5 is applied automatically).",
            host,
            values.get("webbox_rpc_status"),
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


async def _rpc_get_parameters(
    session,
    host: str,
    password: str | None,
    device_key: str,
    channels: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """GetParameter for the given channel names. Empty dict on error/reject."""
    names = [c for c in channels if c]
    if not names:
        return {}
    body, _ = await _rpc_call(
        session,
        host,
        "GetParameter",
        password=password,
        params={"devices": [{"key": device_key, "channels": names}]},
        timeout=15,
    )
    envelope = _parse_rpc_envelope(body or "")
    if not body or not envelope or "error" in envelope:
        return {}
    return parse_rpc_parameters(body)


async def _resolve_si_device_key(
    session,
    host: str,
    *,
    password: str | None,
    device_key: str | None,
) -> str | None:
    """Return a Sunny Island WebBox device key, discovering via GetDevices."""
    key = (device_key or "").strip() or None
    if key:
        return key
    dev_body, status = await _rpc_call(
        session, host, "GetDevices", password=password
    )
    devices = parse_rpc_devices(dev_body or "")
    si_keys = [k for k in devices if k.upper().startswith("SI")]
    targets = si_keys or devices
    if not targets:
        _LOGGER.warning(
            "WebBox RPC: no devices on %s (%s)", host, status
        )
        return None
    return targets[0]


async def async_write_bat_typ_rpc(
    session,
    host: str,
    value: str,
    *,
    password: str | None = None,
    device_key: str | None = None,
    skip_if_current: bool = False,
) -> bool:
    """Write SI BatTyp via WebBox SetParameter (official firmware strings).

    Same path as GdManStr. No Modbus register is used — none is documented
    in this repo or SMA public docs for BatTyp.
    """
    typ = value_to_bat_typ(value)
    host = (host or "").strip()
    if not host:
        raise ValueError("WebBox host is empty")

    key = await _resolve_si_device_key(
        session, host, password=password, device_key=device_key
    )
    if not key:
        return False

    if skip_if_current:
        gp_body, _ = await _rpc_call(
            session,
            host,
            "GetParameter",
            password=password,
            params={
                "devices": [{"key": key, "channels": [BAT_TYP_CHANNEL]}]
            },
            timeout=15,
        )
        current = parse_rpc_parameters(gp_body or "").get("webbox_bat_typ")
        if current == typ:
            _LOGGER.info(
                "WebBox BatTyp already %s on %s device=%s — skip write",
                typ,
                host,
                key,
            )
            return True

    body, status = await _rpc_call(
        session,
        host,
        "SetParameter",
        password=password,
        params={
            "devices": [
                {
                    "key": key,
                    "channels": [{"meta": BAT_TYP_CHANNEL, "value": typ}],
                }
            ]
        },
        timeout=20,
    )
    if not body:
        _LOGGER.warning(
            "WebBox BatTyp RPC write failed value=%s host=%s status=%s",
            typ,
            host,
            status,
        )
        return False

    envelope = _parse_rpc_envelope(body)
    if not envelope or "error" in envelope:
        err = (envelope or {}).get("error") if isinstance(envelope, dict) else None
        _LOGGER.warning(
            "WebBox BatTyp RPC error value=%s host=%s err=%s body=%s",
            typ,
            host,
            err,
            (body or "")[:200],
        )
        return False

    parsed = parse_rpc_parameters(body)
    echoed = parsed.get("webbox_bat_typ")
    if echoed and echoed != typ:
        _LOGGER.warning(
            "WebBox BatTyp RPC wrote %s but device returned %s on %s",
            typ,
            echoed,
            host,
        )
        return False

    _LOGGER.info(
        "WebBox BatTyp RPC → BatTyp=%s on %s device=%s",
        typ,
        host,
        key,
    )
    return True


async def async_write_voltage_rpc(
    session,
    host: str,
    param: str,
    value: Any,
    *,
    password: str | None = None,
    device_key: str | None = None,
) -> tuple[bool, float]:
    """Write one SI voltage channel via WebBox SetParameter.

    Same path as GdManStr / BatTyp. No Modbus register is used.
    """
    spec, num = value_to_voltage(param, value)
    payload = format_voltage_rpc_value(num)
    host = (host or "").strip()
    if not host:
        raise ValueError("WebBox host is empty")

    key = await _resolve_si_device_key(
        session, host, password=password, device_key=device_key
    )
    if not key:
        return False, num

    body, status = await _rpc_call(
        session,
        host,
        "SetParameter",
        password=password,
        params={
            "devices": [
                {
                    "key": key,
                    "channels": [{"meta": spec["channel"], "value": payload}],
                }
            ]
        },
        timeout=20,
    )
    if not body:
        _LOGGER.warning(
            "WebBox %s RPC write failed value=%s host=%s status=%s",
            spec["channel"],
            payload,
            host,
            status,
        )
        return False, num

    envelope = _parse_rpc_envelope(body)
    if not envelope or "error" in envelope:
        err = (envelope or {}).get("error") if isinstance(envelope, dict) else None
        _LOGGER.warning(
            "WebBox %s RPC error value=%s host=%s err=%s body=%s",
            spec["channel"],
            payload,
            host,
            err,
            (body or "")[:200],
        )
        return False, num

    parsed = parse_rpc_parameters(body)
    echoed = parsed.get(spec["sensor_key"])
    if echoed is not None and abs(float(echoed) - num) > 0.051:
        _LOGGER.warning(
            "WebBox %s RPC wrote %s but device returned %s on %s",
            spec["channel"],
            payload,
            echoed,
            host,
        )
        return False, num

    _LOGGER.info(
        "WebBox %s RPC → %s=%s on %s device=%s",
        spec["channel"],
        spec["channel"],
        payload,
        host,
        key,
    )
    return True, num


# Keys sourced from GetParameter / SetParameter — prefer over Modbus when present.
RPC_PARAMETER_KEYS = frozenset(
    {
        "webbox_grid_man_str",
        "webbox_grid_control_option",
        "webbox_grid_control",
        "webbox_grid_control_code",
        "webbox_bat_typ",
        *SI_VOLTAGE_SENSOR_KEYS,
    }
)


def merge_modbus_without_clobbering_rpc_params(
    http_values: dict[str, Any], mb_values: dict[str, Any]
) -> dict[str, Any]:
    """Merge Modbus onto HTTP/RPC; keep RPC parameter-sourced values."""
    out = dict(http_values)
    protect = {
        key
        for key in RPC_PARAMETER_KEYS
        if out.get(key) not in (None, "")
    }
    # Mixed grid-control sources are worse than leaving Modbus 40527 unused.
    if out.get("webbox_grid_man_str") or out.get("webbox_grid_control_option"):
        protect.update(
            {
                "webbox_grid_man_str",
                "webbox_grid_control_option",
                "webbox_grid_control",
                "webbox_grid_control_code",
            }
        )
    for key, val in mb_values.items():
        if key in protect:
            continue
        out[key] = val
    return out


def apply_grid_control_optimistic(values: dict[str, Any], mode: str) -> str:
    """Update runtime values after a successful write; returns mode id."""
    man = mode_to_grid_man_str(mode)
    apply_grid_man_str(values, man)
    return GRID_MAN_STR_TO_OPTION[man]


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
