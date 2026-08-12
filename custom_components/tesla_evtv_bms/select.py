"""Select entities — WebBox grid control (manual start / auto / off)."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE_ENTITY
from .runtime import PackRuntime
from .webbox import apply_grid_control_optimistic, async_set_grid_control
from .webbox_modbus import (
    GRID_CONTROL_OPTION_LABELS,
    GRID_CONTROL_OPTIONS,
    grid_control_option_from_code,
)

_LOGGER = logging.getLogger(__name__)

OPTION_ORDER = ("automatic", "manual_on", "off")


def _get_runtime(hass: HomeAssistant, name: str) -> PackRuntime:
    raw = hass.data.get(DOMAIN, {}).get(name)
    if isinstance(raw, PackRuntime):
        return raw
    raise RuntimeError(f"PackRuntime missing for {name}")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    name = entry.data["name"].lower()
    runtime = _get_runtime(hass, name)
    # Select works via RPC SetParameter even when Modbus is off / 40527 illegal
    if not (runtime.webbox.get("host") or "").strip():
        return

    entity = WebboxGridControlSelect(runtime, name)
    runtime.entities["webbox_grid_control_select"] = entity
    async_add_entities([entity])

    @callback
    def _on_update(values: dict) -> None:
        entity.handle_values(values)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_UPDATE_ENTITY.format(name), _on_update
        )
    )


class WebboxGridControlSelect(SelectEntity):
    """Manual utility-grid control via WebBox SetParameter (GdManStr).

    Falls back to Modbus register 40527 when RPC is unavailable.
    """

    _attr_icon = "mdi:transmission-tower"
    _attr_should_poll = False

    def __init__(self, runtime: PackRuntime, device_name: str) -> None:
        self._runtime = runtime
        prefix = runtime.entity_prefix
        self._attr_unique_id = f"{prefix}_webbox_grid_control_select"
        self.entity_id = f"select.{prefix}_webbox_grid_control"
        self._attr_name = f"{device_name} WebBox Grid Control"
        self._attr_options = [GRID_CONTROL_OPTION_LABELS[k] for k in OPTION_ORDER]
        self._option_ids = list(OPTION_ORDER)
        self._current_id: str | None = None

    @property
    def current_option(self) -> str | None:
        if self._current_id is None:
            return None
        return GRID_CONTROL_OPTION_LABELS.get(self._current_id)

    def handle_values(self, values: dict) -> None:
        opt = values.get("webbox_grid_control_option")
        if opt is None and "webbox_grid_control_code" in values:
            opt = grid_control_option_from_code(values.get("webbox_grid_control_code"))
        if opt is None or opt not in GRID_CONTROL_OPTIONS:
            return
        if opt == self._current_id:
            return
        self._current_id = opt
        self.async_write_ha_state()

    def _label_to_id(self, option: str) -> str | None:
        for oid in self._option_ids:
            if GRID_CONTROL_OPTION_LABELS[oid] == option or oid == option:
                return oid
        # loose match
        key = option.strip().lower().replace(" ", "_")
        if key in GRID_CONTROL_OPTIONS:
            return key
        if "manual" in key or key in ("on", "start", "request"):
            return "manual_on"
        if "auto" in key:
            return "automatic"
        if key == "off":
            return "off"
        return None

    async def async_select_option(self, option: str) -> None:
        mode = self._label_to_id(option)
        if mode is None:
            raise HomeAssistantError(f"Unknown grid control option: {option}")
        cfg = self._runtime.webbox
        host = (cfg.get("host") or "").strip()
        if not host:
            raise HomeAssistantError("WebBox host not configured")

        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(self.hass)
        device_key = (
            cfg.get("device_key")
            or self._runtime.values.get("webbox_device_key")
            or None
        )
        try:
            ok = await async_set_grid_control(
                session,
                host,
                mode,
                password=cfg.get("password") or None,
                device_key=device_key,
                use_modbus=bool(cfg.get("modbus", True)),
                modbus_port=int(cfg.get("port", 502)),
                unit_device=int(cfg.get("unit_device", 3)),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        if not ok:
            raise HomeAssistantError(
                f"Grid control write failed → {mode} on {host} "
                "(RPC SetParameter GdManStr / Modbus 40527)"
            )
        apply_grid_control_optimistic(self._runtime.values, mode)
        self._current_id = mode
        self.async_write_ha_state()
