"""Pure calculation functions for Tesla EVTV BMS.

No Home Assistant dependencies — fully unit-testable.

Sign policy lives in ``signs.py`` (single source of truth).
"""

from typing import Any

from .const import DEFAULT_PACK_SIZE, DEFAULT_CELLS_IN_SERIES
from .signs import flow_from_power, status_label

ENERGY_STATE_KEY = "energy_state"
CELLS_PER_MODULE = 6


def resolve_cells_in_series(values: dict[str, Any], config: dict[str, Any]) -> int:
    """Series cell count for pack voltage (S-count).

    Priority:
    1. **User-configured cells_in_series** — e.g. 2 Tesla modules in series = 12S
       (each module is 6S). CAN 0x68F may still report every module on the bus
       (e.g. 36) even when only two are series-stacked electrically.
    2. total_cells from CAN 0x68F (modules × 6) when no config
    3. total_modules × 6 from CAN 0x68F
    4. active_cells from CAN 0x651 when it looks like a series count (≥ 6)
    5. Default
    """
    configured = config.get("cells_in_series")
    if isinstance(configured, (int, float)) and int(configured) > 0:
        return int(configured)

    total_cells = values.get("total_cells")
    if isinstance(total_cells, (int, float)) and total_cells > 0:
        return int(total_cells)

    total_modules = values.get("total_modules")
    if isinstance(total_modules, (int, float)) and total_modules > 0:
        return int(total_modules) * CELLS_PER_MODULE

    active = values.get("active_cells")
    if isinstance(active, (int, float)) and active >= CELLS_PER_MODULE:
        return int(active)

    if isinstance(active, (int, float)) and active > 0:
        return int(active)

    return DEFAULT_CELLS_IN_SERIES


def _volts_plausible_for_series(volts: float, cells_series: int) -> bool:
    """True if volts implies a sane Li-ion per-cell voltage for the S-count.

    For 12S (2×6S modules) pack V is ~36–50 V. For a long series string it is
    hundreds of volts. Reject values that imply <2 V or >5 V per series cell.
    """
    if cells_series is None or cells_series < 1:
        return True
    per_cell = float(volts) / int(cells_series)
    return 2.0 <= per_cell <= 5.0


def resolve_current(values: dict[str, Any]) -> float | None:
    """Prefer high-res 0x151 current; fall back to integer 0x150 current."""
    current = values.get("current")
    if isinstance(current, (int, float)):
        return float(current)
    coarse = values.get("current_150")
    if isinstance(coarse, (int, float)):
        return float(coarse)
    return None


# Seconds without a 0x651 pack summary before 0x68F recompute may own pack min/max/avg.
STALE_651_S = 15.0
PACK_CELL_KEYS = ("lowest_cell", "highest_cell", "average_cell")


def recompute_cells_from_modules(module_map: dict[int, list[float]]) -> dict[str, Any] | None:
    """Build pack-wide lowest/highest/average from 0x68F per-module cell lists.

    Returns only pack cell statistics — never total_cells/active_cells (those come
    from BMS frames / config, not from a partial module scan map).
    """
    if not module_map:
        return None
    all_cells: list[float] = []
    for cells in module_map.values():
        if cells:
            all_cells.extend(float(c) for c in cells)
    if not all_cells:
        return None
    lo = min(all_cells)
    hi = max(all_cells)
    return {
        "lowest_cell": round(lo, 3),
        "highest_cell": round(hi, 3),
        "average_cell": round(sum(all_cells) / len(all_cells), 3),
        "cell_difference": round(hi - lo, 4),
    }


def merge_cell_frame(
    frame: dict[str, Any],
    modules: dict[int, list[float]],
    last_651: float | None,
    now: float,
    *,
    stale_after_s: float = STALE_651_S,
) -> tuple[dict[str, Any], float | None]:
    """Merge one CAN frame under a simple pack-cell ownership model.

    Ownership:
      * **0x651** owns pack ``lowest_cell`` / ``highest_cell`` / ``average_cell``
        (millivolt summary). Sets ``last_651 = now``.
      * **0x68F** only updates ``modules``. Pack min/max/avg are filled from the
        module map **only when 0x651 is missing or older than** ``stale_after_s``.

    Private keys (``_can_id``, ``_module_idx``, ``_module_cells``) are stripped
    from the returned merge dict. ``modules`` is updated in place for 0x68F.

    Returns ``(merge_dict, new_last_651)``.
    """
    out = dict(frame)
    can_id = out.pop("_can_id", None)
    module_idx = out.pop("_module_idx", None)
    module_cells = out.pop("_module_cells", None)

    new_last_651 = last_651
    if can_id == 0x651:
        new_last_651 = now

    if module_idx is not None and module_cells is not None:
        modules[int(module_idx)] = list(module_cells)
        age = None if new_last_651 is None else (now - float(new_last_651))
        if age is None or age >= stale_after_s:
            recomputed = recompute_cells_from_modules(modules)
            if recomputed:
                for key in PACK_CELL_KEYS:
                    out[key] = recomputed[key]
        # When 0x651 is fresh, do not write pack cell stats from 0x68F.

    return out, new_last_651


def derive_volts_and_power(values: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Derive pack voltage and power. Returns only computed keys.

    Priority for pack voltage:
      1. CAN 0x655 float volts when plausible for S-count (best live accuracy, 0.01 V)
      2. average_cell × configured S-count (e.g. 3.51 × 12 ≈ 42 V for 2 modules)
      3. CAN 0x150 volts when plausible for that S-count (0.1 V native)
      4. any other plausible CAN volts key
    Never accept an implausible CAN voltage (e.g. 0x151 ~750 V on a 12S pack).
    Power is always pack_volts × resolved current.
    """
    derived: dict[str, Any] = {}
    cells_series = resolve_cells_in_series(values, config)
    avg_cell = values.get("average_cell")
    can_volts = values.get("volts")
    can_150 = values.get("can_150_volts")
    can_655 = values.get("can_655_volts")

    cell_pack_volts = None
    if avg_cell is not None and cells_series:
        # 0.01 V so pack volts track live average_cell mV
        cell_pack_volts = round(float(avg_cell) * int(cells_series), 2)

    def _accept_can(v, ndigits: int = 1) -> float | None:
        if not isinstance(v, (int, float)) or v <= 0:
            return None
        can_v = round(float(v), ndigits)
        if cells_series and not _volts_plausible_for_series(can_v, cells_series):
            return None
        return can_v

    # Prefer 0x655 float V (2 decimals), then cell×S, then plausible CAN 0x150
    for candidate in (
        _accept_can(can_655, 2),
        cell_pack_volts if cell_pack_volts is not None
        and _volts_plausible_for_series(cell_pack_volts, cells_series)
        else None,
        _accept_can(can_150, 1),
        _accept_can(can_volts, 1),
        cell_pack_volts,
    ):
        if candidate is not None:
            derived["volts"] = candidate
            break

    current = resolve_current(values)
    if current is not None:
        derived["current"] = round(current, 2)

    volts = derived.get("volts")
    if current is not None and volts is not None:
        derived["power"] = round(float(volts) * float(current))
    return derived


def get_battery_status(current: float | None) -> str:
    return status_label(current)


def split_charge_discharge(power: float | None) -> tuple[float, float]:
    """Return (discharge_W, charge_W) using signs.flow_from_power."""
    if power is None:
        return 0.0, 0.0
    flow = flow_from_power(power)
    mag = abs(float(power))
    if flow == "discharge":
        return mag, 0.0
    if flow == "charge":
        return 0.0, mag
    return 0.0, 0.0


def compute_available_energy(soc: float | None, pack_size: float) -> float | None:
    if soc is None:
        return None
    return round(pack_size * soc / 100, 2)


def compute_cell_difference(values: dict[str, Any]) -> float | None:
    if all(k in values for k in ("highest_cell", "lowest_cell")):
        return round(values["highest_cell"] - values["lowest_cell"], 4)
    return None


def compute_trigger_cell_voltage(values: dict[str, Any], soc: float | None) -> float | None:
    if soc is None:
        return None
    if soc >= 75 and "highest_cell" in values:
        return values["highest_cell"]
    if soc <= 25 and "lowest_cell" in values:
        return values["lowest_cell"]
    if "average_cell" in values:
        return values["average_cell"]
    return None


def accumulate_energy(
    power: float | None,
    delta_seconds: float,
    prev_charge: float = 0.0,
    prev_discharge: float = 0.0,
) -> dict[str, float | str | None]:
    charge = prev_charge
    discharge = prev_discharge
    increment = 0.0
    flow = None
    if power is not None and delta_seconds > 0:
        increment = (abs(power) * delta_seconds / 3600) / 1000
        flow = flow_from_power(power, idle_band=0.0)
        if flow == "discharge":
            discharge += increment
        elif flow == "charge":
            charge += increment
        else:
            flow = None
            increment = 0.0
    return {
        "charge": charge,
        "discharge": discharge,
        "increment": increment,
        "flow": flow,
    }


def compute_derived_state(
    raw: dict[str, Any],
    config: dict[str, Any],
    *,
    prev_energy: dict[str, float] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    derived = derive_volts_and_power(raw, config)
    view = {**raw, **derived}

    pack_size = config.get("pack_size", DEFAULT_PACK_SIZE)
    soc = view.get("state_of_charge")
    current = view.get("current")  # resolved in derive_volts_and_power
    power = view.get("power")

    if soc is not None:
        derived["available_energy"] = compute_available_energy(soc, pack_size)

    if current is not None:
        derived["battery_status"] = get_battery_status(current)

    if power is not None:
        discharge, charge = split_charge_discharge(power)
        derived["discharge"] = discharge
        derived["charge"] = charge

    cell_diff = compute_cell_difference(view)
    if cell_diff is not None:
        derived["cell_difference"] = cell_diff

    trig = compute_trigger_cell_voltage(view, soc)
    if trig is not None:
        derived["trigger_cell_voltage"] = trig

    if prev_energy is not None and now is not None and power is not None:
        last = prev_energy.get("last_update", now)
        delta = max(0.0, now - last)
        # Cap absurd gaps (e.g. after suspend) so one tick can't dump hours of kWh
        if delta > 120.0:
            delta = 0.0
        energy = accumulate_energy(
            power,
            delta,
            prev_energy.get("charge", 0.0),
            prev_energy.get("discharge", 0.0),
        )
        # Keep full float precision in runtime — only round for HA display.
        # Rounding to 3dp every UDP tick (~0.1 s) zeros sub-Wh increments on
        # period meters (3 kW × 0.1 s ≈ 0.000083 kWh → rounds to 0).
        derived["charge_energy"] = float(energy["charge"])
        derived["discharge_energy"] = float(energy["discharge"])
        derived[ENERGY_STATE_KEY] = {
            "charge": energy["charge"],
            "discharge": energy["discharge"],
            "last_update": now,
            "increment": energy["increment"],
            "flow": energy["flow"],
        }

    return derived


UTILITY_METER_PERIODS = ("hour", "day", "week", "month", "year")


def apply_period_energy_increments(
    values: dict[str, Any],
    energy_state: dict[str, Any],
    periods: tuple[str, ...] = UTILITY_METER_PERIODS,
) -> None:
    """Add this tick's kWh increment to hour/day/week/month/year accumulators.

    Full float precision — do not round here (see compute_derived_state).
    """
    flow = energy_state.get("flow")
    increment = energy_state.get("increment", 0.0)
    if not flow or not increment:
        return
    base = "discharge_energy" if flow == "discharge" else "charge_energy"
    for label in periods:
        meter_key = f"{base}_{label}"
        prev = values.get(meter_key, 0.0)
        try:
            prev_f = float(prev)
        except (TypeError, ValueError):
            prev_f = 0.0
        values[meter_key] = prev_f + float(increment)


def apply_derived_state(
    values: dict[str, Any],
    derived: dict[str, Any],
    coordinator_energy: dict[str, float] | None = None,
) -> None:
    for key, val in derived.items():
        if key == ENERGY_STATE_KEY:
            continue
        values[key] = val

    energy_state = derived.get(ENERGY_STATE_KEY)
    if energy_state and coordinator_energy is not None:
        coordinator_energy["charge"] = energy_state["charge"]
        coordinator_energy["discharge"] = energy_state["discharge"]
        coordinator_energy["last_update"] = energy_state["last_update"]
        apply_period_energy_increments(values, energy_state)


def update_rolling_samples(samples: list[float], new_power: float | None, window: int) -> list[float]:
    if new_power is None:
        return list(samples)
    new_samples = list(samples) + [new_power]
    if len(new_samples) > window:
        new_samples = new_samples[-window:]
    return new_samples


def compute_rolling_average(samples: list[float]) -> float | None:
    if not samples:
        return None
    return round(sum(samples) / len(samples), 1)


def compute_hours_to(
    avg_power: float | None,
    status: str,
    available_energy: float,
    pack_size: float,
) -> dict[str, float]:
    hours_empty = 0.0
    hours_full = 0.0
    if avg_power is not None and abs(avg_power) > 0:
        rate_kw = abs(avg_power) / 1000.0
        if status == "Discharging":
            hours_empty = round(available_energy / rate_kw, 2)
        elif status == "Charging":
            hours_full = round((pack_size - available_energy) / rate_kw, 2)
    return {"hours_to_empty": hours_empty, "hours_to_full": hours_full}


def compute_summary(status: str, hours_to_empty: float, hours_to_full: float) -> str:
    if status == "Discharging":
        hrs = hours_to_empty
        hrs_str = f"{hrs:.1f}" if hrs < 10 else f"{int(hrs)}"
        return f"{hrs_str} hrs to Empty"
    if status == "Charging":
        hrs = hours_to_full
        hrs_str = f"{hrs:.1f}" if hrs < 10 else f"{int(hrs)}"
        return f"{hrs_str} hrs to Full"
    return "Idle"