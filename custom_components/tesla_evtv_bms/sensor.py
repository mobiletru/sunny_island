import logging
import time

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval, async_track_time_change

from .const import (
    CONF_WEBBOX_HOST,
    DOMAIN,
    SIGNAL_UPDATE_ENTITY,
    WEBBOX_SENSOR_KEYS,
)
from .runtime import PackRuntime, ROLLING_SPECS
from .calculations import (
    UTILITY_METER_PERIODS,
    apply_derived_state,
    compute_derived_state,
    merge_cell_frame,
    update_rolling_samples,
    compute_rolling_average,
    compute_hours_to,
    compute_summary,
)

_LOGGER = logging.getLogger(__name__)

# Allowlist: only these keys become HA sensors (default-deny for everything else).
SENSOR_TYPES = {
    "state_of_charge": "%",
    "power": "W",
    "current": "A",
    "volts": "V",
    "lowest_cell": "V",
    "highest_cell": "V",
    "average_cell": "V",
    "max_cells": "",
    "active_cells": "",
    "freq_shift_volts": "V",
    "tcch_amps": "A",
    "battery_status": "",
    "charge": "W",
    "discharge": "W",
    "charge_energy": "kWh",
    "discharge_energy": "kWh",
    "available_energy": "kWh",
    "charge_energy_hour": "kWh",
    "charge_energy_day": "kWh",
    "charge_energy_week": "kWh",
    "charge_energy_month": "kWh",
    "charge_energy_year": "kWh",
    "discharge_energy_hour": "kWh",
    "discharge_energy_day": "kWh",
    "discharge_energy_week": "kWh",
    "discharge_energy_month": "kWh",
    "discharge_energy_year": "kWh",
    "cell_difference": "V",
    "trigger_cell_voltage": "V",
    "power_average": "W",
    "power_hourly_average": "W",
    "hours_to_empty": "h",
    "hours_to_full": "h",
    "lowest_temp": "°C",
    "highest_temp": "°C",
    "pack_ah_used": "Ah",
    "high_voltage_cutoff": "V",
    "low_voltage_cutoff": "V",
    "contactor_negative": "",
    "contactor_positive": "",
    "charge_enable": "",
    "heat_enable": "",
    "power_source": "",
    "fault_code": "",
    "fault_status": "",
    "total_modules": "",
    "total_cells": "",
    "summary": "",
    "webbox_power": "W",
    "webbox_daily_yield": "kWh",
    "webbox_total_yield": "kWh",
}

ICON_MAP = {
    "state_of_charge": "mdi:battery",
    "power": "mdi:flash",
    "current": "mdi:current-dc",
    "volts": "mdi:car-battery",
    "lowest_cell": "mdi:battery-low",
    "highest_cell": "mdi:battery-high",
    "average_cell": "mdi:battery-medium",
    "max_cells": "mdi:grid",
    "active_cells": "mdi:checkbox-multiple-marked-circle",
    "freq_shift_volts": "mdi:waveform",
    "tcch_amps": "mdi:current-ac",
    "charge": "mdi:transmission-tower-import",
    "discharge": "mdi:transmission-tower-export",
    "charge_energy": "mdi:transmission-tower-import",
    "discharge_energy": "mdi:transmission-tower-export",
    "available_energy": "mdi:battery-charging-70",
    "charge_energy_hour": "mdi:transmission-tower-import",
    "charge_energy_day": "mdi:transmission-tower-import",
    "charge_energy_week": "mdi:transmission-tower-import",
    "charge_energy_month": "mdi:transmission-tower-import",
    "charge_energy_year": "mdi:transmission-tower-import",
    "discharge_energy_hour": "mdi:transmission-tower-export",
    "discharge_energy_day": "mdi:transmission-tower-export",
    "discharge_energy_week": "mdi:transmission-tower-export",
    "discharge_energy_month": "mdi:transmission-tower-export",
    "discharge_energy_year": "mdi:transmission-tower-export",
    "cell_difference": "mdi:arrow-expand-vertical",
    "trigger_cell_voltage": "mdi:transmission-tower",
    "power_average": "mdi:chart-line",
    "power_hourly_average": "mdi:chart-timeline-variant",
    "hours_to_empty": "mdi:battery-alert",
    "hours_to_full": "mdi:battery-clock",
    "lowest_temp": "mdi:thermometer-low",
    "highest_temp": "mdi:thermometer-high",
    "pack_ah_used": "mdi:counter",
    "high_voltage_cutoff": "mdi:arrow-up-bold-circle",
    "low_voltage_cutoff": "mdi:arrow-down-bold-circle",
    "contactor_negative": "mdi:electric-switch",
    "contactor_positive": "mdi:electric-switch",
    "charge_enable": "mdi:battery-plus-variant",
    "heat_enable": "mdi:radiator",
    "power_source": "mdi:power-plug",
    "fault_code": "mdi:numeric",
    "fault_status": "mdi:alert-circle",
    "total_modules": "mdi:cube-outline",
    "total_cells": "mdi:checkbox-multiple-marked-circle",
    "summary": "mdi:clock-outline",
    "webbox_power": "mdi:solar-power",
    "webbox_daily_yield": "mdi:weather-sunny",
    "webbox_total_yield": "mdi:chart-areaspline",
}

WEBBOX_KEY_PREFIXES = ("webbox_",)

_VOLTAGE_KEYS = frozenset(
    {
        "volts",
        "lowest_cell",
        "highest_cell",
        "average_cell",
        "cell_difference",
        "trigger_cell_voltage",
        "high_voltage_cutoff",
        "low_voltage_cutoff",
        "freq_shift_volts",
    }
)
_POWER_KEYS = frozenset(
    {
        "power",
        "charge",
        "discharge",
        "power_average",
        "power_hourly_average",
        "webbox_power",
    }
)
_CURRENT_KEYS = frozenset({"current", "tcch_amps"})
_TEMP_KEYS = frozenset({"lowest_temp", "highest_temp"})
_ENERGY_TOTAL_KEYS = frozenset(
    {
        "charge_energy",
        "discharge_energy",
        "charge_energy_hour",
        "charge_energy_day",
        "charge_energy_week",
        "charge_energy_month",
        "charge_energy_year",
        "discharge_energy_hour",
        "discharge_energy_day",
        "discharge_energy_week",
        "discharge_energy_month",
        "discharge_energy_year",
        "webbox_daily_yield",
        "webbox_total_yield",
    }
)
_CELL_MV_KEYS = frozenset(
    {
        "lowest_cell",
        "highest_cell",
        "average_cell",
        "cell_difference",
        "trigger_cell_voltage",
    }
)
_FAST_COOLDOWN_KEYS = frozenset(
    {
        "lowest_cell",
        "highest_cell",
        "average_cell",
        "cell_difference",
        "trigger_cell_voltage",
        "volts",
        "current",
        "power",
    }
)
_MEASUREMENT_KEYS = (
    _POWER_KEYS
    | _VOLTAGE_KEYS
    | _CURRENT_KEYS
    | _TEMP_KEYS
    | _CELL_MV_KEYS
    | frozenset(
        {
            "state_of_charge",
            "power_average",
            "power_hourly_average",
            "hours_to_empty",
            "hours_to_full",
            "pack_ah_used",
            "available_energy",
        }
    )
)

BOOTSTRAP_KEYS = [
    "charge_energy",
    "discharge_energy",
    "charge_energy_hour",
    "charge_energy_day",
    "charge_energy_week",
    "charge_energy_month",
    "charge_energy_year",
    "discharge_energy_hour",
    "discharge_energy_day",
    "discharge_energy_week",
    "discharge_energy_month",
    "discharge_energy_year",
    "available_energy",
    "power",
    "current",
    "volts",
    "state_of_charge",
    "battery_status",
    "lowest_cell",
    "highest_cell",
    "average_cell",
    "fault_status",
    "summary",
    "power_average",
    "power_hourly_average",
    "hours_to_empty",
    "hours_to_full",
]


def is_public_sensor_key(key: str) -> bool:
    return key in SENSOR_TYPES


def sensor_device_class(key: str):
    if key == "available_energy":
        return SensorDeviceClass.ENERGY_STORAGE
    if key in _ENERGY_TOTAL_KEYS or key.endswith("_energy") or "_energy_" in key:
        return SensorDeviceClass.ENERGY
    if key in _POWER_KEYS:
        return SensorDeviceClass.POWER
    if key in _VOLTAGE_KEYS:
        return SensorDeviceClass.VOLTAGE
    if key in _CURRENT_KEYS:
        return SensorDeviceClass.CURRENT
    if key in _TEMP_KEYS:
        return SensorDeviceClass.TEMPERATURE
    if key == "state_of_charge":
        return SensorDeviceClass.BATTERY
    return None


def sensor_state_class(key: str):
    if key == "available_energy":
        return SensorStateClass.MEASUREMENT
    if key in _ENERGY_TOTAL_KEYS or key.endswith("_energy") or "_energy_" in key:
        return SensorStateClass.TOTAL_INCREASING
    if key in _MEASUREMENT_KEYS:
        return SensorStateClass.MEASUREMENT
    return None


def sensor_display_precision(key: str) -> int | None:
    if key in _CELL_MV_KEYS:
        return 3
    if key in _ENERGY_TOTAL_KEYS or key == "available_energy":
        return 3
    if key in ("volts", "freq_shift_volts", "high_voltage_cutoff", "low_voltage_cutoff"):
        return 2
    if key in _CURRENT_KEYS:
        return 2
    return None


def sensor_cooldown(key: str) -> float:
    return 0.25 if key in _FAST_COOLDOWN_KEYS else 1.0


def _values_same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def _get_runtime(hass: HomeAssistant, name: str) -> PackRuntime:
    raw = hass.data.get(DOMAIN, {}).get(name)
    if isinstance(raw, PackRuntime):
        return raw
    raise RuntimeError(f"PackRuntime missing for {name}")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    name = entry.data["name"].lower()
    runtime = _get_runtime(hass, name)
    prefix = runtime.entity_prefix

    def _schedule_entity(entity):
        if entity is None or getattr(entity, "hass", None) is None:
            return
        try:
            entity.async_write_ha_state()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "write_ha_state failed for %s", entity.entity_id, exc_info=True
            )

    async def add_sensor_entity(key, unit=None):
        if not is_public_sensor_key(key):
            return None
        if key in runtime.entities:
            return runtime.entities[key]
        unit = unit if unit is not None else SENSOR_TYPES.get(key, "")
        sensor = TeslaEvtvSensor(name, key, unit, runtime, prefix)
        runtime.entities[key] = sensor
        async_add_entities([sensor])
        return sensor

    bootstrap = list(BOOTSTRAP_KEYS)
    webbox_host = (entry.data.get(CONF_WEBBOX_HOST) or "").strip()
    if webbox_host:
        bootstrap.extend(WEBBOX_SENSOR_KEYS)
        for key in WEBBOX_SENSOR_KEYS:
            runtime.values.setdefault(key, None)
    for key in bootstrap:
        await add_sensor_entity(key)

    async def handle_update(values):
        before = dict(runtime.values)
        now_mono = time.monotonic()

        merged, last_651 = merge_cell_frame(
            values,
            runtime.modules,
            runtime.last_651_cells,
            now_mono,
        )
        runtime.last_651_cells = last_651
        runtime.values.update(merged)

        energy = runtime.ensure_energy()
        derived = compute_derived_state(
            runtime.values,
            runtime.config,
            prev_energy=energy,
            now=now_mono,
        )
        apply_derived_state(runtime.values, derived, energy)

        for key in list(runtime.values.keys()):
            if is_public_sensor_key(key):
                await add_sensor_entity(key)

        now = time.monotonic()
        for key, entity in list(runtime.entities.items()):
            if getattr(entity, "hass", None) is None:
                continue
            new_val = runtime.values.get(key)
            old_val = before.get(key)
            if _values_same(new_val, old_val) and (now - entity._last_update) < entity._cooldown:
                continue
            entity._last_update = now
            _schedule_entity(entity)

    unsub_dispatcher = async_dispatcher_connect(
        hass,
        SIGNAL_UPDATE_ENTITY.format(name),
        handle_update,
    )
    entry.async_on_unload(unsub_dispatcher)

    def create_utility_updater(base_key):
        for label in UTILITY_METER_PERIODS:
            runtime.values.setdefault(f"{base_key}_{label}", 0.0)

        async def reset_meter(meter_key):
            runtime.values[meter_key] = 0.0
            entity = runtime.entities.get(meter_key)
            if entity is not None and getattr(entity, "hass", None) is not None:
                entity.async_schedule_update_ha_state()

        async def hourly(now, base=base_key):
            await reset_meter(f"{base}_hour")

        async def daily(now, base=base_key):
            await reset_meter(f"{base}_day")
            if now.weekday() == 0:
                await reset_meter(f"{base}_week")
            if now.day == 1:
                await reset_meter(f"{base}_month")
                if now.month == 1:
                    await reset_meter(f"{base}_year")

        entry.async_on_unload(
            async_track_time_change(hass, hourly, minute=0, second=0)
        )
        entry.async_on_unload(
            async_track_time_change(hass, daily, hour=0, minute=0, second=0)
        )

    create_utility_updater("discharge_energy")
    create_utility_updater("charge_energy")

    def track_rolling_averages(interval_key):
        interval_info = runtime.rolling[interval_key]

        async def updater(now):
            power = runtime.values.get("power")
            interval_info["samples"] = update_rolling_samples(
                interval_info["samples"], power, interval_info["window"]
            )
            avg = compute_rolling_average(interval_info["samples"])
            if avg is None:
                return
            runtime.values[interval_key] = avg
            await add_sensor_entity(interval_key, "W")
            _schedule_entity(runtime.entities.get(interval_key))

            status = runtime.values.get("battery_status", "")
            available_energy = runtime.values.get("available_energy", 0) or 0
            pack_size = runtime.config["pack_size"]

            hours = compute_hours_to(avg, status, available_energy, pack_size)
            runtime.values["hours_to_empty"] = hours["hours_to_empty"]
            runtime.values["hours_to_full"] = hours["hours_to_full"]

            await add_sensor_entity("hours_to_empty", "h")
            await add_sensor_entity("hours_to_full", "h")
            _schedule_entity(runtime.entities.get("hours_to_empty"))
            _schedule_entity(runtime.entities.get("hours_to_full"))

            summary_value = compute_summary(
                status,
                runtime.values["hours_to_empty"],
                runtime.values["hours_to_full"],
            )
            runtime.values["summary"] = summary_value
            await add_sensor_entity("summary", "")
            _schedule_entity(runtime.entities.get("summary"))

        entry.async_on_unload(
            async_track_time_interval(hass, updater, interval_info["interval"])
        )

    for key in ROLLING_SPECS:
        track_rolling_averages(key)


class TeslaEvtvSensor(SensorEntity, RestoreEntity):
    """One public BMS / WebBox value."""

    def __init__(self, device_name, key, unit, runtime: PackRuntime, entity_prefix: str):
        self._device = device_name
        self._key = key
        self._unit = unit
        self._runtime = runtime
        self._entity_prefix = entity_prefix
        self._state = None
        self._last_update = 0
        self._cooldown = sensor_cooldown(key)
        self._attr_unique_id = f"{entity_prefix}_{key}"
        self.entity_id = f"sensor.{entity_prefix}_{key}"
        self._attr_name = f"{device_name} {key.replace('_', ' ').title()}"
        self._attr_icon = ICON_MAP.get(key, "mdi:chip")
        self._attr_native_unit_of_measurement = unit or None
        self._attr_device_class = sensor_device_class(key)
        self._attr_state_class = sensor_state_class(key)
        precision = sensor_display_precision(key)
        if precision is not None:
            self._attr_suggested_display_precision = precision

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def native_value(self):
        val = self._runtime.values.get(self._key)
        if val is None:
            return None
        # Display kWh to 3 dp; runtime keeps full float so tiny UDP ticks accumulate
        if self._key in _ENERGY_TOTAL_KEYS or self._key == "available_energy":
            try:
                return round(float(val), 3)
            except (TypeError, ValueError):
                return val
        return val

    @property
    def available(self) -> bool:
        if self._key.startswith(WEBBOX_KEY_PREFIXES):
            return True
        return self._key in self._runtime.values

    @property
    def icon(self):
        soc = self.native_value
        if self._key == "state_of_charge" and soc is not None:
            try:
                soc = float(soc)
            except (TypeError, ValueError):
                return ICON_MAP.get(self._key, "mdi:chip")
            for threshold, icon in zip(
                [90, 80, 70, 60, 50, 40, 30, 20, 10],
                [
                    "mdi:battery",
                    "mdi:battery-90",
                    "mdi:battery-80",
                    "mdi:battery-70",
                    "mdi:battery-60",
                    "mdi:battery-50",
                    "mdi:battery-40",
                    "mdi:battery-30",
                    "mdi:battery-20",
                    "mdi:battery-alert",
                ],
            ):
                if soc >= threshold:
                    return icon
        return ICON_MAP.get(self._key, "mdi:chip")

    @property
    def device_info(self):
        if self._key.startswith(WEBBOX_KEY_PREFIXES):
            device_id = f"{self._device}_webbox"
            return {
                "identifiers": {(DOMAIN, device_id)},
                "name": "SMA Sunny WebBox",
                "manufacturer": "SMA Solar Technology",
                "model": "Sunny WebBox",
                "entry_type": "service",
                "suggested_area": "Solar",
                "via_device": (DOMAIN, self._device),
            }
        display = " ".join(w.capitalize() for w in self._device.split())
        return {
            "identifiers": {(DOMAIN, self._device)},
            "name": display or self._device,
            "manufacturer": "EVTV",
            "model": "Tesla BMS (2-line 12S)",
            "entry_type": "service",
            "suggested_area": "Battery Storage",
        }

    async def async_added_to_hass(self):
        old_state = await self.async_get_last_state()
        if old_state and old_state.state not in (None, "unknown", "unavailable", ""):
            try:
                self._runtime.values[self._key] = float(old_state.state)
            except ValueError:
                self._runtime.values[self._key] = old_state.state
