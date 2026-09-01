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


def _reg(key: str):
    for row in mb.WEBBOX_MODBUS_REGISTERS:
        if row[0] == key:
            return row
    raise AssertionError(f"missing register {key}")


def test_registers_include_core_params_not_sunny_boy():
    keys = {row[0] for row in mb.WEBBOX_MODBUS_REGISTERS}
    assert "webbox_power" in keys
    assert "webbox_grid_voltage" in keys
    assert "webbox_battery_voltage" in keys
    assert "webbox_device_power" in keys
    assert "webbox_grid_connection_time" in keys
    assert "webbox_grid_control_code" in keys
    assert "webbox_operating_status_code" in keys
    assert "webbox_power_setpoint_timeout" in keys
    # Sunny Boy-only — blank or pinned on SI6048; derive instead of poll.
    assert "webbox_apparent_power" not in keys
    assert "webbox_reactive_power" not in keys
    assert "webbox_grid_relay_code" not in keys
    addrs = {row[2] for row in mb.WEBBOX_MODBUS_REGISTERS}
    assert 30805 not in addrs
    assert 30813 not in addrs
    assert 30217 not in addrs
    assert 30865 not in addrs


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
    # Raw SMA FIX3 (+discharge). Plant tile uses the flipped table scale.
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


def test_30845_is_soc_not_voltage_and_not_30865():
    """Live plant: 30845=45–46 was shown as V; 30865 SoC sat at 0%."""
    key, _unit, addr, count, dtype, scale = _reg("webbox_battery_soc")
    assert key == "webbox_battery_soc"
    assert addr == 30845
    assert count == 2
    assert dtype == "u32"
    assert scale == 1.0
    assert _reg("webbox_battery_voltage")[2] == 30851
    assert 30865 not in {row[2] for row in mb.WEBBOX_MODBUS_REGISTERS}
    assert mb._decode_regs([0, 45], "u32", 1.0) == 45
    assert mb._decode_regs([0, 43], "u32", 1.0) == 43


def test_30851_voltage_fix2_matches_12s_pack():
    """Live pack 42.07–42.10 V is U32 FIX2 on 30851, not whole-volt 30845."""
    _key, _unit, addr, _count, dtype, scale = _reg("webbox_battery_voltage")
    assert addr == 30851
    assert dtype == "u32"
    assert scale == 0.01
    val = mb._decode_regs([0, 4210], dtype, scale)
    assert abs(val - 42.10) < 1e-9
    val_lo = mb._decode_regs([0, 4207], dtype, scale)
    assert abs(val_lo - 42.07) < 1e-9


def test_30843_current_sign_flipped_to_plant_convention():
    """SMA 30843 is +discharge FIX3. Plant legend is − discharge / + charge."""
    _key, _unit, addr, _count, dtype, scale = _reg("webbox_battery_current")
    assert addr == 30843
    assert dtype == "s32"
    assert scale == -0.001
    # Live: SMA raw +156000 (FIX3, +discharge) while pack current was −156 A.
    raw_dis = 156000
    discharge = mb._decode_regs([(raw_dis >> 16) & 0xFFFF, raw_dis & 0xFFFF], dtype, scale)
    assert abs(discharge - (-156.0)) < 1e-9
    # SMA −45000 raw = charging 45 A; plant sign flip → +45 A.
    raw_charge = (-45000) & 0xFFFFFFFF
    charge = mb._decode_regs(
        [(raw_charge >> 16) & 0xFFFF, raw_charge & 0xFFFF], dtype, scale
    )
    assert abs(charge - 45.0) < 1e-9


def test_30849_temp_is_celsius_fix1():
    """72.3 is SI sensor °C FIX1, not °F and not Tesla brick temp."""
    _key, _unit, addr, _count, dtype, scale = _reg("webbox_battery_temp")
    assert addr == 30849
    assert dtype == "u32"
    assert scale == 0.1
    assert abs(mb._decode_regs([0, 723], dtype, scale) - 72.3) < 1e-9


def test_apply_si_modbus_derived_relay_apparent_clears_reactive():
    out = mb.apply_si_modbus_derived(
        {"webbox_operating_status_code": 1463, "webbox_device_power": -6700}
    )
    assert out["webbox_grid_relay"] == "Open"
    assert out["webbox_apparent_power"] == 6700
    assert out["webbox_reactive_power"] is None

    grid = mb.apply_si_modbus_derived(
        {"webbox_operating_status": "Parallel grid", "webbox_power": -100}
    )
    assert grid["webbox_grid_relay"] == "Closed"
    assert grid["webbox_apparent_power"] == 100
    # Stale Sunny Boy Q must not survive a poll that no longer reads 30805.
    stale = mb.apply_si_modbus_derived({})
    assert stale["webbox_reactive_power"] is None


def test_30783_kept_and_30903_is_external_grid_voltage():
    """30783 stays InvVtg; Grid V tile is ExtVtg 30903 (WEBBOX-MODBUS-TB-EN-19)."""
    inv = _reg("webbox_inverter_voltage")
    assert inv[2] == 30783
    assert inv[4] == "u32"
    assert inv[5] == 0.01
    assert abs(mb._decode_regs([0, 12098], "u32", 0.01) - 120.98) < 1e-9

    ext = _reg("webbox_grid_voltage")
    assert ext[2] == 30903
    assert ext[4] == "u32"
    assert ext[5] == 0.01
    assert abs(mb._decode_regs([0, 12098], "u32", 0.01) - 120.98) < 1e-9

    assert _reg("webbox_grid_voltage_l2")[2] == 30905
    assert _reg("webbox_inverter_voltage_l2")[2] == 30785


def test_30909_extcur_signed_not_pack_flipped():
    """ExtCur S32 FIX3 — SMA signed import/export, not pack −discharge/+charge."""
    key, _u, addr, _c, dtype, scale = _reg("webbox_grid_current")
    assert addr == 30909
    assert dtype == "s32"
    assert scale == 0.001
    assert scale > 0  # must not use the 30843 pack flip
    import_a = mb._decode_regs([0, 18500], dtype, scale)
    assert abs(import_a - 18.5) < 1e-9
    raw_neg = (-12300) & 0xFFFFFFFF
    export_a = mb._decode_regs(
        [(raw_neg >> 16) & 0xFFFF, raw_neg & 0xFFFF], dtype, scale
    )
    assert abs(export_a - (-12.3)) < 1e-9
    assert _reg("webbox_grid_current_l2")[2] == 30911
    assert _reg("webbox_grid_current_l2")[5] == 0.001
    addrs = {row[2] for row in mb.WEBBOX_MODBUS_REGISTERS}
    assert 30795 not in addrs  # TotInvCur — inverter, not external grid


def test_ext_voltage_falls_back_to_30783_when_islanded():
    out = mb.apply_si_modbus_derived({"webbox_inverter_voltage": 120.98})
    assert out["webbox_grid_voltage"] == 120.98
    kept = mb.apply_si_modbus_derived(
        {"webbox_grid_voltage": 121.4, "webbox_inverter_voltage": 120.98}
    )
    assert kept["webbox_grid_voltage"] == 121.4
