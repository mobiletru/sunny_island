"""Per-config-entry runtime state for Tesla EVTV BMS.

One PackRuntime per pack/port. Owns values, energy accumulator, module map,
rolling averages, and entity registry — not module-global mutable state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .const import pack_config_from_data
from .calculations import UTILITY_METER_PERIODS


DEFAULT_ENTITY_PREFIX = "battery_storage_tesla_pack"

ROLLING_SPECS: dict[str, dict[str, Any]] = {
    "power_average": {"interval": timedelta(minutes=1), "window": 10},
    "power_hourly_average": {"interval": timedelta(minutes=5), "window": 12},
}


def entity_prefix_from_data(data: dict) -> str:
    """Stable entity/unique_id prefix from config entry data."""
    raw = (data.get("entity_prefix") or DEFAULT_ENTITY_PREFIX).strip()
    # Allow only safe entity_id characters
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in raw.lower())
    cleaned = cleaned.strip("_") or DEFAULT_ENTITY_PREFIX
    return cleaned


@dataclass
class PackRuntime:
    """Mutable runtime bag for one BMS pack."""

    name: str
    entity_prefix: str
    config: dict[str, Any]
    entities: dict[str, Any] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)
    modules: dict[int, list[float]] = field(default_factory=dict)
    last_651_cells: float | None = None
    energy: dict[str, float] | None = None
    energy_seeded: bool = False
    socket: Any = None
    loop: Any = None
    rolling: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_entry_data(cls, data: dict) -> PackRuntime:
        name = str(data["name"]).lower()
        prefix = entity_prefix_from_data(data)
        rt = cls(
            name=name,
            entity_prefix=prefix,
            config=pack_config_from_data(data),
        )
        for key, spec in ROLLING_SPECS.items():
            rt.rolling[key] = {
                "interval": spec["interval"],
                "window": spec["window"],
                "samples": [],
            }
        for base in ("charge_energy", "discharge_energy"):
            for label in UTILITY_METER_PERIODS:
                rt.values.setdefault(f"{base}_{label}", 0.0)
        return rt

    def ensure_energy(self) -> dict[str, float]:
        """Return energy accumulator, lifting from restored sensor values.

        Restore may finish after the first UDP tick. Always raise the
        accumulator to match TOTAL_INCREASING restored values when higher.
        """
        if self.energy is None:
            self.energy = {
                "charge": 0.0,
                "discharge": 0.0,
                "last_update": time.monotonic(),
            }

        for value_key, field in (
            ("charge_energy", "charge"),
            ("discharge_energy", "discharge"),
        ):
            raw = self.values.get(value_key)
            if isinstance(raw, (int, float)) and float(raw) > float(self.energy[field]):
                self.energy[field] = float(raw)
                self.energy_seeded = True

        return self.energy

    def to_hass_data(self) -> dict[str, Any]:
        """Back-compat mapping used by older call sites / tests."""
        return {
            "entities": self.entities,
            "values": self.values,
            "config": self.config,
            "modules": self.modules,
            "last_651_cells": self.last_651_cells,
            "energy": self.energy,
            "socket": self.socket,
            "loop": self.loop,
            "entity_prefix": self.entity_prefix,
            "runtime": self,
            "rolling": self.rolling,
        }
