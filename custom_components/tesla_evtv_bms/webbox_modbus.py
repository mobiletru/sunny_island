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
