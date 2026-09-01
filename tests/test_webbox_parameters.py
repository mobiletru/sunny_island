"""Tests for WebBox GetParameter / SetParameter (GdManStr) helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "tesla_evtv_bms"


def _load_webbox():
    pkg = "tesla_evtv_bms"
    if pkg not in sys.modules:
        m = types.ModuleType(pkg)
        m.__path__ = [str(COMPONENT)]
        sys.modules[pkg] = m
    full = f"{pkg}.webbox"
    if full in sys.modules:
        # reload for fresh source
        del sys.modules[full]
    path = COMPONENT / "webbox.py"
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


wb = _load_webbox()


def test_normalize_grid_man_str_aliases():
    assert wb.normalize_grid_man_str("Start") == "Start"
    assert wb.normalize_grid_man_str("manual_on") == "Start"
    assert wb.normalize_grid_man_str("auto") == "Auto"
    assert wb.normalize_grid_man_str("off") == "Stop"
    assert wb.normalize_grid_man_str("---") is None


def test_mode_to_grid_man_str():
    assert wb.mode_to_grid_man_str("manual_on") == "Start"
    assert wb.mode_to_grid_man_str("automatic") == "Auto"
    assert wb.mode_to_grid_man_str("off") == "Stop"


def test_apply_grid_control_optimistic():
    values = {}
    mode = wb.apply_grid_control_optimistic(values, "manual_on")
    assert mode == "manual_on"
    assert values["webbox_grid_man_str"] == "Start"
    assert values["webbox_grid_control_option"] == "manual_on"
    assert values["webbox_grid_control_code"] == 308
    assert values["webbox_grid_control"] == "Manual On"


def test_parse_rpc_parameters_gdmanstr():
    body = (
        '{"result":{"devices":[{"key":"SI6048","channels":'
        '[{"meta":"GdManStr","value":"Auto"}]}]},"version":"1.0"}'
    )
    out = wb.parse_rpc_parameters(body)
    assert out["webbox_grid_man_str"] == "Auto"
    assert out["webbox_grid_control_option"] == "automatic"
    assert out["webbox_grid_control_code"] == 1438


def test_merge_modbus_keeps_rpc_params():
    http = {
        "webbox_grid_man_str": "Start",
        "webbox_grid_control_option": "manual_on",
        "webbox_grid_control": "Manual On",
        "webbox_grid_control_code": 308,
        "webbox_power": -100,
    }
    mb = {
        "webbox_grid_control_code": 303,
        "webbox_grid_control": "Off",
        "webbox_grid_control_option": "off",
        "webbox_battery_soc": 55,
    }
    out = wb.merge_modbus_without_clobbering_rpc_params(http, mb)
    assert out["webbox_grid_control_option"] == "manual_on"
    assert out["webbox_grid_control_code"] == 308
    assert out["webbox_battery_soc"] == 55
    assert out["webbox_power"] == -100


def test_rpc_process_map_has_extcur():
    assert wb.RPC_PROCESS_MAP["ExtCur"][0] == "webbox_grid_current"
    assert wb.RPC_PROCESS_MAP["ExtCurSlv1"][0] == "webbox_grid_current_l2"
    assert wb.RPC_PROCESS_MAP["ExtVtg"][0] == "webbox_grid_voltage"
    assert wb.RPC_PROCESS_MAP["ExtVtgSlv1"][0] == "webbox_grid_voltage_l2"


def test_merge_then_derived_fills_relay_and_clears_reactive():
    from tesla_evtv_bms import webbox_modbus as mb

    http = {
        "webbox_operating_status": "Backup",
        "webbox_power": -6700,
        "webbox_grid_man_str": "Auto",
        "webbox_grid_control_option": "automatic",
    }
    mb_vals = {
        "webbox_battery_soc": 43,
        "webbox_battery_voltage": 42.10,
        "webbox_battery_current": -156.0,
        "webbox_grid_control_code": 303,
    }
    out = wb.merge_modbus_without_clobbering_rpc_params(http, mb_vals)
    mb.apply_si_modbus_derived(out)
    assert out["webbox_grid_control_option"] == "automatic"
    assert out["webbox_battery_soc"] == 43
    assert out["webbox_grid_relay"] == "Open"
    assert out["webbox_apparent_power"] == 6700
    assert out["webbox_reactive_power"] is None


def test_password_hash_sma():
    # Documented WebBox default access password (plain "sma" → MD5 hex)
    h = wb.webbox_password_hash("sma")
    assert len(h) == 32
    assert h == "a289fa4252ed5af8e3e9f9bee545c172"


def test_render_rpc_keeps_charge_voltage_decimals():
    spec = wb.RPC_PARAM_SPECS["charge_voltage_full"]
    rendered, stored = wb._render_rpc_value(spec, "2.27")
    assert rendered == "2.27"
    assert stored == 2.27
    # UI Math.round(2.27) used to send "2" — still a valid number, but wrong.
    rendered_int, stored_int = wb._render_rpc_value(spec, "2")
    assert rendered_int == "2.00"
    assert stored_int == 2.0


def test_render_rpc_keeps_grid_hz_tenths():
    spec = wb.RPC_PARAM_SPECS["grid_frequency_min"]
    rendered, stored = wb._render_rpc_value(spec, "59.3")
    assert rendered == "59.3"
    assert stored == 59.3
