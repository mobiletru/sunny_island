"""Canonical current/power sign policy for this pack.

LiteCAN raw amps are left as the BMS reports them. On this plant, negative
current means energy is leaving the pack (SoC falls). Status, charge/discharge
split, and kWh accumulation all use this module — nowhere else redefines the
sign.
"""

from __future__ import annotations

from typing import Literal

# True  → negative amps/power = discharge (this Sunny Island / Tesla bank)
# False → positive amps/power = discharge (classic EVTV LiteCAN docs)
DISCHARGE_IS_NEGATIVE = True

Flow = Literal["charge", "discharge", "idle"]


def flow_from_current(current: float | None, *, idle_band: float = 1.0) -> Flow:
    if current is None:
        return "idle"
    c = float(current)
    if abs(c) <= idle_band:
        return "idle"
    if DISCHARGE_IS_NEGATIVE:
        return "discharge" if c < 0 else "charge"
    return "discharge" if c > 0 else "charge"


def flow_from_power(power: float | None, *, idle_band: float = 1.0) -> Flow:
    if power is None:
        return "idle"
    p = float(power)
    if abs(p) <= idle_band:
        return "idle"
    if DISCHARGE_IS_NEGATIVE:
        return "discharge" if p < 0 else "charge"
    return "discharge" if p > 0 else "charge"


def status_label(current: float | None) -> str:
    flow = flow_from_current(current)
    if flow == "discharge":
        return "Discharging"
    if flow == "charge":
        return "Charging"
    return "Idle"
