"""Tests for WebBox Modbus register decode (no network)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "tesla_evtv_bms"


def _load():
    pkg = "tesla_evtv_bms"
    if pkg not in sys.modules:
        m = types.ModuleType(pkg)
        m.__path__ = [str(COMPONENT)]
        sys.modules[pkg] = m
    full = f"{pkg}.webbox_modbus"
    if full in sys.modules:
        return sys.modules[full]
    path = COMPONENT / "webbox_modbus.py"
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


mb = _load()


def test_decode_s32_power():
    # -100 W as observed on plant WebBox
    val = mb._decode_regs([65535, 65436], "s32", 1.0)
    assert val == -100


def test_decode_u32_grid_hz():
    val = mb._decode_regs([0, 5999], "u32", 0.01)
    assert abs(val - 59.99) < 1e-6


def test_decode_u64_daily_yield_kwh():
    # 6300 Wh → 6.3 kWh
    val = mb._decode_regs([0, 0, 0, 6300], "u64", 0.001)
    assert abs(val - 6.3) < 1e-6


def test_status_labels():
    assert mb.status_label(307) == "OK"
    assert mb.grid_relay_label(51) == "Closed"
    assert mb.grid_relay_label(0) == "Open"


def test_registers_include_apparent_and_core_params():
    keys = {row[0] for row in mb.WEBBOX_MODBUS_REGISTERS}
    assert "webbox_power" in keys
    assert "webbox_apparent_power" in keys
    assert "webbox_grid_voltage" in keys
    assert "webbox_battery_voltage" in keys
    assert "webbox_device_power" in keys
    assert "webbox_grid_connection_time" in keys
    assert "webbox_grid_control_code" in keys
    assert "webbox_operating_status_code" in keys


def test_power_kw_derived_from_plant_power():
    # Simulate post-process: -1500 W → -1.5 kW
    out = {"webbox_power": -1500}
    out["webbox_power_kw"] = round(float(out["webbox_power"]) / 1000.0, 3)
    assert out["webbox_power_kw"] == -1.5


def test_grid_control_codes_and_labels():
    assert mb.GRID_CONTROL_OPTIONS["manual_on"] == 308
    assert mb.GRID_CONTROL_OPTIONS["automatic"] == 1438
    assert mb.GRID_CONTROL_OPTIONS["off"] == 303
    assert mb.grid_control_label(308) == "Manual On"
    assert mb.grid_control_option_from_code(1438) == "automatic"
    assert mb.operating_status_label(235) == "Parallel grid"
    assert mb.operating_status_label(1463) == "Backup"


def test_si_parameter_registers_and_labels():
    keys = {row[0] for row in mb.WEBBOX_MODBUS_REGISTERS}
    assert "webbox_battery_current" in keys
    assert "webbox_discharge_limit" in keys
    assert "webbox_reverse_feed_code" in keys
    assert "webbox_feed_soc_upper" in keys
    assert "webbox_feed_soc_lower" in keys
    assert "webbox_power_setpoint_mode_code" in keys
    assert mb.reverse_feed_label(1129) == "Yes"
    assert mb.reverse_feed_label(1130) == "No"
    assert mb.power_setpoint_mode_label(1079) == "External"
    # FIX3 battery current
    val = mb._decode_regs([0, 1500], "s32", 0.001)
    assert abs(val - 1.5) < 1e-9


def test_decode_u64_nan_all_ones():
    assert mb._decode_regs([0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF], "u64", 0.001) is None


def test_write_holding_u32_pdu_shape():
    """FC16 encoding: two registers big-endian for value 308."""
    import struct

    value = 308
    hi = (value >> 16) & 0xFFFF
    lo = value & 0xFFFF
    pdu = struct.pack(">BHHBHH", 0x10, mb.GRID_CONTROL_REG, 2, 4, hi, lo)
    assert pdu[0] == 0x10
    assert struct.unpack(">H", pdu[1:3])[0] == 40527
    assert struct.unpack(">HH", pdu[-4:]) == (0, 308)
