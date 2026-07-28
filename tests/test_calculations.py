"""Unit tests for pure BMS math (no Home Assistant).

Loads sibling modules by file path so package __init__.py (HA imports) is skipped.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "tesla_evtv_bms"


def _load(mod_name: str, file_name: str, package: str = "tesla_evtv_bms"):
    """Load a module file under a synthetic package namespace."""
    pkg_name = package
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        sys.modules[pkg_name] = pkg

    full = f"{pkg_name}.{mod_name}"
    if full in sys.modules:
        return sys.modules[full]

    path = COMPONENT / file_name
    spec = importlib.util.spec_from_file_location(full, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    setattr(sys.modules[pkg_name], mod_name, mod)
    return mod


# Load pure modules (order matters for relative imports)
const = _load("const", "const.py")
signs = _load("signs", "signs.py")
calculations = _load("calculations", "calculations.py")
parser = _load("parser", "parser.py")
webbox = _load("webbox", "webbox.py")
runtime = _load("runtime", "runtime.py")


def test_decode_module_cell_byte():
    assert parser.decode_module_cell_byte(0x7A) == 3.22
    assert parser.decode_module_cell_byte(0x82) == 3.30


def test_signs_discharge_is_negative():
    assert signs.flow_from_current(-5.0) == "discharge"
    assert signs.flow_from_current(5.0) == "charge"
    assert signs.flow_from_current(0.5) == "idle"
    assert signs.flow_from_power(-100.0) == "discharge"
    assert signs.status_label(-10.0) == "Discharging"


def test_resolve_cells_configured_wins():
    values = {"total_cells": 216, "total_modules": 36}
    config = {"cells_in_series": 12}
    assert calculations.resolve_cells_in_series(values, config) == 12


def test_derive_volts_prefers_cell_times_s_over_implausible_can():
    values = {
        "average_cell": 3.50,
        "can_151_volts": 750.0,
        "current": -12.0,
    }
    config = {"cells_in_series": 12}
    derived = calculations.derive_volts_and_power(values, config)
    assert derived["volts"] == 42.0
    assert derived["power"] == round(42.0 * -12.0)


def test_merge_cell_frame_651_owns_until_stale():
    modules: dict = {}
    frame_651 = {
        "_can_id": 0x651,
        "lowest_cell": 3.2,
        "highest_cell": 3.4,
        "average_cell": 3.3,
    }
    out, last = calculations.merge_cell_frame(frame_651, modules, None, now=100.0)
    assert last == 100.0
    assert out["lowest_cell"] == 3.2

    frame_68f = {
        "_can_id": 0x68F,
        "_module_idx": 0,
        "_module_cells": [3.0, 3.0, 3.0, 3.0, 3.0, 3.0],
    }
    out2, last2 = calculations.merge_cell_frame(frame_68f, modules, last, now=101.0)
    assert last2 == 100.0
    assert "lowest_cell" not in out2
    assert 0 in modules

    out3, _ = calculations.merge_cell_frame(
        frame_68f, modules, last, now=200.0, stale_after_s=15.0
    )
    assert out3["lowest_cell"] == 3.0


def test_recompute_cells_from_modules():
    stats = calculations.recompute_cells_from_modules(
        {0: [3.1, 3.2, 3.3, 3.4, 3.5, 3.6]}
    )
    assert stats["lowest_cell"] == 3.1
    assert stats["highest_cell"] == 3.6


def test_energy_accumulate_and_seed():
    rt = runtime.PackRuntime.from_entry_data(
        {
            "name": "Pack",
            "entity_prefix": "battery_storage_tesla_pack",
            "pack_size": 75,
            "cells_in_series": 12,
        }
    )
    rt.values["charge_energy"] = 12.5
    rt.values["discharge_energy"] = 8.25
    energy = rt.ensure_energy()
    assert energy["charge"] == 12.5
    assert energy["discharge"] == 8.25

    rt2 = runtime.PackRuntime.from_entry_data(
        {"name": "Pack", "pack_size": 75, "cells_in_series": 12}
    )
    e2 = rt2.ensure_energy()
    assert e2["charge"] == 0.0
    rt2.values["charge_energy"] = 99.0
    e2b = rt2.ensure_energy()
    assert e2b["charge"] == 99.0

    acc = calculations.accumulate_energy(
        -1000.0, 3600.0, prev_charge=0.0, prev_discharge=0.0
    )
    assert acc["flow"] == "discharge"
    assert abs(acc["increment"] - 1.0) < 1e-9


def test_compute_derived_state_applies_energy():
    raw = {
        "state_of_charge": 50.0,
        "average_cell": 3.5,
        "current": -10.0,
    }
    config = {"pack_size": 75.0, "cells_in_series": 12}
    prev = {"charge": 1.0, "discharge": 2.0, "last_update": 0.0}
    derived = calculations.compute_derived_state(
        raw, config, prev_energy=prev, now=3600.0
    )
    values = dict(raw)
    energy = dict(prev)
    calculations.apply_derived_state(values, derived, energy)
    assert values["volts"] == 42.0
    assert values["battery_status"] == "Discharging"
    assert energy["discharge"] > 2.0


def test_entity_prefix_sanitized():
    assert runtime.entity_prefix_from_data({}) == "battery_storage_tesla_pack"
    assert runtime.entity_prefix_from_data({"entity_prefix": "My Pack!"}) == "my_pack"


def test_parse_overview_ajax():
    payload = {
        "Items": [
            {"Power": "-900 W"},
            {"DailyYield": "8.2 kWh"},
            {"TotalYield": "5348.2 kWh"},
        ]
    }
    out = webbox.parse_overview_ajax(payload)
    assert out["webbox_power"] == -900.0
    assert out["webbox_daily_yield"] == 8.2


def test_parse_udp_soc_frame():
    payload = bytearray(12)
    payload[0] = 100  # SoC raw → 50.0%
    payload[8] = 0x50
    payload[9] = 0x06
    result = parser.parse_udp_packet(bytes(payload), 6850)
    assert result is not None
    assert result["state_of_charge"] == 50.0


def run_all() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"OK  {name}")
        except Exception as exc:
            fails += 1
            print(f"FAIL {name}: {exc}")
    return fails


if __name__ == "__main__":
    raise SystemExit(run_all())
