"""Async Modbus TCP client for SMA Sunny WebBox (no pymodbus dependency).

Reads gateway (unit 1), plant (unit 2), and first device/SI (unit 3) holding
registers over Modbus TCP (MBAP). Supports FC03 read and FC16 write of U32
parameters (e.g. manual grid control). Used as a WebBox proxy so plant
parameters appear on the Tesla EVTV BMS / Sunny Island integration entities.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

_LOGGER = logging.getLogger(__name__)

# (sensor_key, unit_id, address, count, dtype, scale)
# dtype: u32 | s32 | u64 | s64
WEBBOX_MODBUS_REGISTERS: tuple[tuple[str, int, int, int, str, float], ...] = (
    # Gateway
    ("webbox_modbus_profile", 1, 30001, 2, "u32", 1.0),
    ("webbox_serial", 1, 30057, 2, "u32", 1.0),
    # Plant overview via WebBox proxy
    ("webbox_power", 2, 30775, 2, "s32", 1.0),  # W — also filled by HTTP
    ("webbox_daily_yield", 2, 30517, 4, "u64", 0.001),  # Wh → kWh
    ("webbox_total_yield", 2, 30513, 4, "u64", 0.001),  # Wh → kWh
    # Device / Sunny Island on RS485 behind WebBox
    ("webbox_device_power", 3, 30775, 2, "s32", 1.0),
    ("webbox_grid_voltage", 3, 30783, 2, "s32", 0.01),
    ("webbox_grid_frequency", 3, 30803, 2, "u32", 0.01),
    ("webbox_reactive_power", 3, 30805, 2, "s32", 0.01),  # FIX2 (var)
    ("webbox_apparent_power", 3, 30813, 2, "s32", 1.0),
    ("webbox_status_code", 3, 30201, 2, "s32", 1.0),
    ("webbox_grid_relay_code", 3, 30217, 2, "u32", 1.0),
    # Grid start / connection
    ("webbox_grid_connection_time", 3, 30199, 2, "u32", 1.0),  # s until attempt
    ("webbox_operating_status_code", 3, 33003, 2, "u32", 1.0),
    ("webbox_generator_status_code", 3, 30917, 2, "u32", 1.0),
    # Manual control of utility grid: 303=Off · 308=On · 1438=Automatic
    ("webbox_grid_control_code", 3, 40527, 2, "u32", 1.0),
    ("webbox_operating_time", 3, 30541, 2, "u32", 1.0),
    # SI battery (this plant: bus V on 30845 FIX0; SoC 30865; SI profile also has 30843/30851)
    ("webbox_battery_voltage", 3, 30845, 2, "s32", 1.0),
    ("webbox_battery_soc", 3, 30865, 2, "u32", 1.0),
    ("webbox_battery_temp", 3, 30849, 2, "s32", 0.1),
    ("webbox_battery_current", 3, 30843, 2, "s32", 0.001),  # A FIX3
    # SI parameters (SoC limits / feed-in / power-setpoint mode)
    ("webbox_discharge_limit", 3, 31009, 2, "u32", 1.0),  # % self-consumption floor
    ("webbox_reverse_feed_code", 3, 40679, 2, "u32", 1.0),  # 1129 Yes · 1130 No
    ("webbox_feed_soc_upper", 3, 40705, 2, "u32", 1.0),  # % reactivate feed-in
    ("webbox_feed_soc_lower", 3, 40707, 2, "u32", 1.0),  # % block feed-in
    ("webbox_power_setpoint_timeout", 3, 41195, 2, "u32", 1.0),  # s
    ("webbox_power_setpoint_mode_code", 3, 40210, 2, "u32", 1.0),
    ("webbox_device_serial", 3, 30057, 2, "u32", 1.0),
    ("webbox_device_susy_id", 3, 30053, 2, "u32", 1.0),
)

# SMA TAGLIST / ENUM codes
STATUS_LABELS = {
    307: "OK",
    303: "Off",
    455: "Warning",
    35: "Fault",
}

OPERATING_STATUS_LABELS = {
    235: "Parallel grid",
    1463: "Backup",
    2677: "Generator",
    3664: "Emergency charge",
    16777213: "N/A",
}

GENERATOR_STATUS_LABELS = {
    303: "Off",
    1392: "Error",
    1787: "Initialization",
    1788: "Ready",
    1789: "Warm-up",
    1790: "Synchronize",
    1791: "Activated",
    1792: "Re-synchronize",
    1793: "Generator separation",
    1794: "Shut-off delay",
    1795: "Blocked",
    1796: "Locked after error",
    16777213: "N/A",
}

# Manual control of the utility grid (register 40527)
GRID_CONTROL_OFF = 303
GRID_CONTROL_ON = 308  # manual grid request
GRID_CONTROL_AUTO = 1438
GRID_CONTROL_REG = 40527

GRID_CONTROL_LABELS = {
    GRID_CONTROL_OFF: "Off",
    GRID_CONTROL_ON: "Manual On",
    GRID_CONTROL_AUTO: "Automatic",
}

# option id → enum code (select entity)
GRID_CONTROL_OPTIONS: dict[str, int] = {
    "off": GRID_CONTROL_OFF,
    "manual_on": GRID_CONTROL_ON,
    "automatic": GRID_CONTROL_AUTO,
}

GRID_CONTROL_OPTION_LABELS: dict[str, str] = {
    "off": "Off",
    "manual_on": "Manual On (request grid)",
    "automatic": "Automatic",
}

# 40679 Reverse-feeding into the utility grid permitted
REVERSE_FEED_LABELS = {
    1129: "Yes",
    1130: "No",
}

# 40210 Operating mode Active power setpoint
POWER_SETPOINT_MODE_LABELS = {
    303: "Off",
    1077: "Manual W",
    1078: "Manual %",
    1079: "External",
}


def _decode_regs(regs: list[int], dtype: str, scale: float) -> float | int | None:
    if not regs:
        return None
    try:
        if dtype in ("u32", "s32") and len(regs) >= 2:
            raw = ((regs[0] & 0xFFFF) << 16) | (regs[1] & 0xFFFF)
            if dtype == "s32" and raw >= 0x80000000:
                raw -= 0x100000000
        elif dtype in ("u64", "s64") and len(regs) >= 4:
            raw = 0
            for w in regs[:4]:
                raw = (raw << 16) | (w & 0xFFFF)
            if dtype == "s64" and raw >= (1 << 63):
                raw -= 1 << 64
        else:
            raw = regs[0] & 0xFFFF
        # SMA NaN / invalid markers
        if dtype == "s32" and raw in (-2147483648,):
            return None
        if dtype == "u32" and raw == 0xFFFFFFFF:
            return None
        if dtype in ("u64", "s64") and raw == (1 << 64) - 1:
            return None
        val = raw * scale
        if scale != 1.0:
            return round(float(val), 6 if scale < 0.01 else 3)
        return int(val) if float(val).is_integer() else float(val)
    except Exception:  # noqa: BLE001
        return None


def _label_map(
    code: float | int | None, labels: dict[int, str], *, fallback_prefix: str = "code"
) -> str | None:
    if code is None:
        return None
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    return labels.get(c, f"{fallback_prefix} {c}")


def status_label(code: float | int | None) -> str | None:
    return _label_map(code, STATUS_LABELS)


def grid_relay_label(code: float | int | None) -> str | None:
    if code is None:
        return None
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    return "Closed" if c == 51 else "Open"


def operating_status_label(code: float | int | None) -> str | None:
    return _label_map(code, OPERATING_STATUS_LABELS)


def generator_status_label(code: float | int | None) -> str | None:
    return _label_map(code, GENERATOR_STATUS_LABELS)


def grid_control_label(code: float | int | None) -> str | None:
    return _label_map(code, GRID_CONTROL_LABELS)


def reverse_feed_label(code: float | int | None) -> str | None:
    return _label_map(code, REVERSE_FEED_LABELS)


def power_setpoint_mode_label(code: float | int | None) -> str | None:
    return _label_map(code, POWER_SETPOINT_MODE_LABELS)


def grid_control_option_from_code(code: float | int | None) -> str | None:
    """Map raw enum → select option id."""
    if code is None:
        return None
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    for opt, val in GRID_CONTROL_OPTIONS.items():
        if val == c:
            return opt
    return None


class AsyncModbusTcp:
    """Minimal Modbus TCP client (FC03 read, FC16 write)."""

    def __init__(self, host: str, port: int = 502, timeout: float = 4.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._txn = 1

    def _next_txn(self) -> int:
        self._txn = (self._txn % 65535) + 1
        return self._txn

    async def _transact(self, unit: int, pdu: bytes) -> bytes | None:
        """Open connection, send MBAP+PDU, return PDU body (no unit byte)."""
        tid = self._next_txn()
        mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit) + pdu
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
        except (OSError, asyncio.TimeoutError) as err:
            _LOGGER.debug("Modbus connect %s:%s failed: %s", self.host, self.port, err)
            return None
        try:
            writer.write(mbap)
            await writer.drain()
            header = await asyncio.wait_for(reader.readexactly(7), timeout=self.timeout)
            _tid, _proto, length, _uid = struct.unpack(">HHHB", header)
            body = await asyncio.wait_for(
                reader.readexactly(max(0, length - 1)), timeout=self.timeout
            )
            if not body:
                return None
            if body[0] & 0x80:
                _LOGGER.debug(
                    "Modbus exception u%s fc=%s code=%s",
                    unit,
                    body[0] & 0x7F,
                    body[1] if len(body) > 1 else "?",
                )
                return None
            return body
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as err:
            _LOGGER.debug("Modbus transact %s u%s: %s", self.host, unit, err)
            return None
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def read_holding(
        self, unit: int, address: int, count: int
    ) -> list[int] | None:
        pdu = struct.pack(">BHH", 0x03, address, count)
        body = await self._transact(unit, pdu)
        if body is None or body[0] != 0x03 or len(body) < 2:
            return None
        bc = body[1]
        data = body[2 : 2 + bc]
        if len(data) < count * 2:
            return None
        return list(struct.unpack(">" + "H" * count, data[: count * 2]))

    async def write_holding_u32(self, unit: int, address: int, value: int) -> bool:
        """FC16 write two registers (SMA U32 big-endian word order)."""
        value = int(value) & 0xFFFFFFFF
        hi = (value >> 16) & 0xFFFF
        lo = value & 0xFFFF
        # FC16: addr, qty=2, byte_count=4, data...
        pdu = struct.pack(">BHHBHH", 0x10, address, 2, 4, hi, lo)
        body = await self._transact(unit, pdu)
        if body is None or body[0] != 0x10 or len(body) < 5:
            return False
        # Echo: address + quantity
        echo_addr, echo_qty = struct.unpack(">HH", body[1:5])
        return echo_addr == address and echo_qty == 2


async def async_poll_webbox_modbus(
    host: str,
    *,
    port: int = 502,
    unit_gateway: int = 1,
    unit_plant: int = 2,
    unit_device: int = 3,
) -> dict[str, Any]:
    """Poll configured registers; returns sensor_key → value."""
    client = AsyncModbusTcp(host, port=port)
    unit_map = {1: unit_gateway, 2: unit_plant, 3: unit_device}
    out: dict[str, Any] = {}
    for key, default_unit, address, count, dtype, scale in WEBBOX_MODBUS_REGISTERS:
        unit = unit_map.get(default_unit, default_unit)
        regs = await client.read_holding(unit, address, count)
        if regs is None:
            continue
        val = _decode_regs(regs, dtype, scale)
        if val is None:
            continue
        out[key] = val

    if "webbox_status_code" in out:
        label = status_label(out["webbox_status_code"])
        if label:
            out["webbox_status"] = label
    if "webbox_grid_relay_code" in out:
        label = grid_relay_label(out["webbox_grid_relay_code"])
        if label:
            out["webbox_grid_relay"] = label
    if "webbox_operating_status_code" in out:
        label = operating_status_label(out["webbox_operating_status_code"])
        if label:
            out["webbox_operating_status"] = label
    if "webbox_generator_status_code" in out:
        label = generator_status_label(out["webbox_generator_status_code"])
        if label:
            out["webbox_generator_status"] = label
    if "webbox_grid_control_code" in out:
        label = grid_control_label(out["webbox_grid_control_code"])
        if label:
            out["webbox_grid_control"] = label
        opt = grid_control_option_from_code(out["webbox_grid_control_code"])
        if opt:
            out["webbox_grid_control_option"] = opt
    if "webbox_reverse_feed_code" in out:
        label = reverse_feed_label(out["webbox_reverse_feed_code"])
        if label:
            out["webbox_reverse_feed"] = label
    if "webbox_power_setpoint_mode_code" in out:
        label = power_setpoint_mode_label(out["webbox_power_setpoint_mode_code"])
        if label:
            out["webbox_power_setpoint_mode"] = label
    # Convenience kW mirror of plant active power (W)
    if "webbox_power" in out and out["webbox_power"] is not None:
        try:
            out["webbox_power_kw"] = round(float(out["webbox_power"]) / 1000.0, 3)
        except (TypeError, ValueError):
            pass
    return out


async def async_write_grid_control(
    host: str,
    mode: str,
    *,
    port: int = 502,
    unit_device: int = 3,
) -> bool:
    """Write manual utility-grid control (40527). mode: off | manual_on | automatic."""
    mode_key = (mode or "").strip().lower().replace(" ", "_").replace("-", "_")
    # Accept friendly aliases
    aliases = {
        "on": "manual_on",
        "manual": "manual_on",
        "start": "manual_on",
        "request": "manual_on",
        "grid": "manual_on",
        "auto": "automatic",
    }
    mode_key = aliases.get(mode_key, mode_key)
    if mode_key not in GRID_CONTROL_OPTIONS:
        raise ValueError(
            f"Unknown grid control mode {mode!r}; "
            f"use one of {sorted(GRID_CONTROL_OPTIONS)}"
        )
    code = GRID_CONTROL_OPTIONS[mode_key]
    client = AsyncModbusTcp(host, port=port)
    ok = await client.write_holding_u32(unit_device, GRID_CONTROL_REG, code)
    if ok:
        _LOGGER.info(
            "WebBox grid control → %s (%s) on %s unit %s",
            mode_key,
            code,
            host,
            unit_device,
        )
    else:
        _LOGGER.warning(
            "WebBox grid control write failed mode=%s host=%s unit=%s",
            mode_key,
            host,
            unit_device,
        )
    return ok


# Writable SI / plant parameters (Modbus holding U32 on unit 3 unless noted).
# value_map: optional friendly option → raw enum code
SI_WRITE_PARAMS: dict[str, dict[str, Any]] = {
    "grid_control": {
        "address": GRID_CONTROL_REG,
        "value_map": {
            **GRID_CONTROL_OPTIONS,
            "on": GRID_CONTROL_ON,
            "manual": GRID_CONTROL_ON,
            "start": GRID_CONTROL_ON,
            "request": GRID_CONTROL_ON,
            "auto": GRID_CONTROL_AUTO,
            "stop": GRID_CONTROL_OFF,
        },
        "sensor_keys": (
            "webbox_grid_control_code",
            "webbox_grid_control",
            "webbox_grid_control_option",
        ),
    },
    "reverse_feed": {
        "address": 40679,
        "value_map": {
            "yes": 1129,
            "no": 1130,
            "on": 1129,
            "off": 1130,
            "true": 1129,
            "false": 1130,
            "1": 1129,
            "0": 1130,
        },
        "sensor_keys": ("webbox_reverse_feed_code", "webbox_reverse_feed"),
    },
    "power_setpoint_mode": {
        "address": 40210,
        "value_map": {
            "off": 303,
            "manual_w": 1077,
            "manual_pct": 1078,
            "manual_%": 1078,
            "external": 1079,
            "w": 1077,
            "pct": 1078,
            "percent": 1078,
        },
        "sensor_keys": (
            "webbox_power_setpoint_mode_code",
            "webbox_power_setpoint_mode",
        ),
    },
    "discharge_limit": {
        "address": 31009,
        "min": 0,
        "max": 100,
        "sensor_keys": ("webbox_discharge_limit",),
    },
    "feed_soc_upper": {
        "address": 40705,
        "min": 0,
        "max": 100,
        "sensor_keys": ("webbox_feed_soc_upper",),
    },
    "feed_soc_lower": {
        "address": 40707,
        "min": 0,
        "max": 100,
        "sensor_keys": ("webbox_feed_soc_lower",),
    },
    "power_setpoint_timeout": {
        "address": 41195,
        "min": 0,
        "max": 86400,
        "sensor_keys": ("webbox_power_setpoint_timeout",),
    },
}


def _resolve_si_write_value(param: str, value: Any) -> int:
    """Resolve friendly / numeric value → U32 holding register payload."""
    spec = SI_WRITE_PARAMS.get(param)
    if not spec:
        raise ValueError(
            f"Unknown SI parameter {param!r}; "
            f"use one of {sorted(SI_WRITE_PARAMS)}"
        )
    raw = value
    if isinstance(raw, str):
        key = raw.strip().lower().replace(" ", "_").replace("-", "_")
        vmap = spec.get("value_map") or {}
        if key in vmap:
            return int(vmap[key])
        # numeric string
        try:
            raw = float(key) if "." in key else int(key)
        except ValueError as err:
            raise ValueError(
                f"Invalid value {value!r} for {param}; "
                f"options={sorted(vmap) if vmap else 'number'}"
            ) from err
    code = int(raw)
    if "min" in spec and code < int(spec["min"]):
        raise ValueError(f"{param} must be ≥ {spec['min']}")
    if "max" in spec and code > int(spec["max"]):
        raise ValueError(f"{param} must be ≤ {spec['max']}")
    return code & 0xFFFFFFFF


def apply_si_parameter_optimistic(
    values: dict[str, Any], param: str, code: int
) -> None:
    """Update runtime sensor bag after a successful write."""
    if param == "grid_control":
        # reuse grid control labels
        for opt, val in GRID_CONTROL_OPTIONS.items():
            if val == code:
                values["webbox_grid_control_option"] = opt
                values["webbox_grid_control_code"] = code
                values["webbox_grid_control"] = GRID_CONTROL_LABELS.get(code, str(code))
                return
    if param == "reverse_feed":
        values["webbox_reverse_feed_code"] = code
        values["webbox_reverse_feed"] = reverse_feed_label(code) or str(code)
        return
    if param == "power_setpoint_mode":
        values["webbox_power_setpoint_mode_code"] = code
        values["webbox_power_setpoint_mode"] = (
            power_setpoint_mode_label(code) or str(code)
        )
        return
    if param == "discharge_limit":
        values["webbox_discharge_limit"] = code
        return
    if param == "feed_soc_upper":
        values["webbox_feed_soc_upper"] = code
        return
    if param == "feed_soc_lower":
        values["webbox_feed_soc_lower"] = code
        return
    if param == "power_setpoint_timeout":
        values["webbox_power_setpoint_timeout"] = code
        return


async def async_write_si_parameter(
    host: str,
    param: str,
    value: Any,
    *,
    port: int = 502,
    unit_device: int = 3,
) -> tuple[bool, int]:
    """Write one SI parameter via Modbus FC16. Returns (ok, raw_code)."""
    param_key = (param or "").strip().lower().replace(" ", "_").replace("-", "_")
    # aliases
    aliases = {
        "grid": "grid_control",
        "gdmanstr": "grid_control",
        "reverse": "reverse_feed",
        "feed_in": "reverse_feed",
        "setpoint_mode": "power_setpoint_mode",
        "sp_mode": "power_setpoint_mode",
        "discharge": "discharge_limit",
        "self_consumption": "discharge_limit",
        "feed_upper": "feed_soc_upper",
        "feed_lower": "feed_soc_lower",
        "sp_timeout": "power_setpoint_timeout",
        "setpoint_timeout": "power_setpoint_timeout",
    }
    param_key = aliases.get(param_key, param_key)
    if param_key == "grid_control":
        # Dedicated writer accepts friendly aliases (start/auto/off/…)
        mode = str(value).strip().lower().replace(" ", "_")
        code = _resolve_si_write_value("grid_control", value)
        ok = await async_write_grid_control(
            host, mode, port=port, unit_device=unit_device
        )
        return ok, code

    code = _resolve_si_write_value(param_key, value)
    address = int(SI_WRITE_PARAMS[param_key]["address"])
    client = AsyncModbusTcp(host, port=port)
    ok = await client.write_holding_u32(unit_device, address, code)
    if ok:
        _LOGGER.info(
            "WebBox SI param %s → %s (addr %s) on %s unit %s",
            param_key,
            code,
            address,
            host,
            unit_device,
        )
    else:
        _LOGGER.warning(
            "WebBox SI param write failed %s=%s host=%s unit=%s addr=%s",
            param_key,
            code,
            host,
            unit_device,
            address,
        )
    return ok, code
