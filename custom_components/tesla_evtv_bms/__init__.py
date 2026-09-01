import asyncio
import logging
import socket
import time
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    ATTR_ENTRY_ID,
    ATTR_HOST,
    ATTR_MODE,
    ATTR_PARAMETER,
    ATTR_PASSWORD,
    ATTR_VALUE,
    CONF_WEBBOX_HOST,
    CONF_WEBBOX_MODBUS,
    CONF_WEBBOX_MODBUS_PORT,
    CONF_WEBBOX_PASSWORD,
    CONF_WEBBOX_SCAN_INTERVAL,
    CONF_WEBBOX_UNIT_DEVICE,
    CONF_WEBBOX_UNIT_GATEWAY,
    CONF_WEBBOX_UNIT_PLANT,
    DEFAULT_WEBBOX_MODBUS,
    DEFAULT_WEBBOX_MODBUS_PORT,
    DEFAULT_WEBBOX_SCAN_INTERVAL,
    DEFAULT_WEBBOX_UNIT_DEVICE,
    DEFAULT_WEBBOX_UNIT_GATEWAY,
    DEFAULT_WEBBOX_UNIT_PLANT,
    DOMAIN,
    PLATFORMS,
    SERVICE_SET_GRID_CONTROL,
    SERVICE_SET_SI_PARAMETER,
    SERVICE_SET_WEBBOX,
    SIGNAL_UPDATE_ENTITY,
    webbox_data_updates,
)
from .parser import parse_udp_packet
from .runtime import PackRuntime
from .webbox import (
    apply_grid_control_optimistic,
    apply_rpc_param_optimistic,
    async_poll_webbox,
    async_set_grid_control,
    async_write_rpc_parameter,
    merge_modbus_without_clobbering_rpc_params,
    resolve_rpc_param,
)
from .webbox_modbus import (
    apply_si_parameter_optimistic,
    async_poll_webbox_modbus,
    async_write_si_parameter,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_GRID_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MODE): cv.string,
        vol.Optional("entity_prefix"): cv.string,
        vol.Optional("name"): cv.string,
    }
)

SERVICE_SET_SI_PARAMETER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PARAMETER): cv.string,
        vol.Required(ATTR_VALUE): vol.Any(cv.string, int, float, bool),
        vol.Optional("entity_prefix"): cv.string,
        vol.Optional("name"): cv.string,
    }
)

SERVICE_SET_WEBBOX_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_HOST): cv.string,
        vol.Optional(ATTR_PASSWORD): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)


async def _write_grid_control_for_runtime(
    hass: HomeAssistant, rt: PackRuntime, mode: str
) -> None:
    """RPC SetParameter (GdManStr) first, then Modbus 40527 if enabled."""
    cfg = rt.webbox
    host = (cfg.get("host") or "").strip()
    if not host:
        raise HomeAssistantError("WebBox host not configured")
    session = async_get_clientsession(hass)
    device_key = (cfg.get("device_key") or rt.values.get("webbox_device_key") or "") or None
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
            f"Grid control write failed on {host} "
            "(RPC SetParameter GdManStr, then Modbus 40527)"
        )
    apply_grid_control_optimistic(rt.values, mode)
    sel = rt.entities.get("webbox_grid_control_select")
    if sel is not None:
        sel.handle_values(rt.values)
        # Push select state into HA immediately after optimistic write
        if getattr(sel, "hass", None) is not None:
            sel.async_write_ha_state()


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def _handle_set_grid_control(call: ServiceCall) -> None:
        mode = call.data[ATTR_MODE]
        prefix = (call.data.get("entity_prefix") or "").strip().lower()
        name_filter = (call.data.get("name") or "").strip().lower()
        packs = hass.data.get(DOMAIN, {})
        targets: list[PackRuntime] = []
        for key, rt in packs.items():
            if not isinstance(rt, PackRuntime):
                continue
            if name_filter and key != name_filter and rt.name != name_filter:
                continue
            # entity_prefix filter (UI / plant app); also accept unique_id style
            if prefix and rt.entity_prefix != prefix and not prefix.endswith(
                rt.entity_prefix
            ):
                continue
            if not (rt.webbox.get("host") or "").strip():
                continue
            targets.append(rt)
        if not targets:
            # If no filter, use all packs with webbox; if filter matched nothing, error
            if name_filter or prefix:
                raise HomeAssistantError(
                    "No matching pack with WebBox host found "
                    f"(prefix={prefix!r} name={name_filter!r})"
                )
            targets = [
                rt
                for rt in packs.values()
                if isinstance(rt, PackRuntime) and (rt.webbox.get("host") or "").strip()
            ]
        if not targets:
            raise HomeAssistantError(
                "No WebBox-enabled pack configured "
                "(set WebBox host on Tesla EVTV BMS → Configure)"
            )
        for rt in targets:
            await _write_grid_control_for_runtime(hass, rt, mode)

    async def _webbox_targets(
        prefix: str, name_filter: str
    ) -> list[PackRuntime]:
        packs = hass.data.get(DOMAIN, {})
        targets: list[PackRuntime] = []
        for key, rt in packs.items():
            if not isinstance(rt, PackRuntime):
                continue
            if name_filter and key != name_filter and rt.name != name_filter:
                continue
            if prefix and rt.entity_prefix != prefix and not prefix.endswith(
                rt.entity_prefix
            ):
                continue
            if not (rt.webbox.get("host") or "").strip():
                continue
            targets.append(rt)
        if not targets:
            if name_filter or prefix:
                raise HomeAssistantError(
                    "No matching pack with WebBox host found "
                    f"(prefix={prefix!r} name={name_filter!r})"
                )
            targets = [
                rt
                for rt in packs.values()
                if isinstance(rt, PackRuntime) and (rt.webbox.get("host") or "").strip()
            ]
        if not targets:
            raise HomeAssistantError(
                "No WebBox-enabled pack configured "
                "(set WebBox host on Tesla EVTV BMS → Configure)"
            )
        return targets

    async def _handle_set_si_parameter(call: ServiceCall) -> None:
        param = call.data[ATTR_PARAMETER]
        value = call.data[ATTR_VALUE]
        prefix = (call.data.get("entity_prefix") or "").strip().lower()
        name_filter = (call.data.get("name") or "").strip().lower()
        targets = await _webbox_targets(prefix, name_filter)
        param_key = str(param).strip().lower().replace(" ", "_").replace("-", "_")
        for rt in targets:
            if param_key in ("grid_control", "grid", "gdmanstr"):
                await _write_grid_control_for_runtime(hass, rt, str(value))
                continue
            cfg = rt.webbox
            host = (cfg.get("host") or "").strip()
            rpc_key = None
            try:
                rpc_key = resolve_rpc_param(param_key)
            except ValueError:
                rpc_key = None
            if rpc_key:
                session = async_get_clientsession(hass)
                device_key = (
                    (cfg.get("device_key") or rt.values.get("webbox_device_key") or "")
                    or None
                )
                try:
                    ok, stored = await async_write_rpc_parameter(
                        session,
                        host,
                        rpc_key,
                        value,
                        password=cfg.get("password") or None,
                        device_key=device_key,
                    )
                except ValueError as err:
                    raise HomeAssistantError(str(err)) from err
                if not ok:
                    raise HomeAssistantError(
                        f"WebBox parameter write failed: {rpc_key}={value!r} on {host}"
                    )
                apply_rpc_param_optimistic(rt.values, rpc_key, stored)
                async_dispatcher_send(
                    hass, SIGNAL_UPDATE_ENTITY.format(rt.name), rt.values
                )
                continue
            if not bool(cfg.get("modbus", True)):
                raise HomeAssistantError(
                    "WebBox Modbus is disabled — enable it to write SI parameters"
                )
            try:
                ok, code = await async_write_si_parameter(
                    host,
                    param_key,
                    value,
                    port=int(cfg.get("port", 502)),
                    unit_device=int(cfg.get("unit_device", 3)),
                )
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            if not ok:
                raise HomeAssistantError(
                    f"SI parameter write failed: {param_key}={value!r} on {host}"
                )
            apply_si_parameter_optimistic(rt.values, param_key, code)
            async_dispatcher_send(
                hass, SIGNAL_UPDATE_ENTITY.format(rt.name), rt.values
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_GRID_CONTROL,
        _handle_set_grid_control,
        schema=SERVICE_SET_GRID_CONTROL_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SI_PARAMETER,
        _handle_set_si_parameter,
        schema=SERVICE_SET_SI_PARAMETER_SCHEMA,
    )

    async def _handle_set_webbox(call: ServiceCall) -> None:
        """Overlay WebBox host/password onto entry.data. Empty fields are omitted."""
        host = call.data.get(ATTR_HOST)
        password = call.data.get(ATTR_PASSWORD)
        entry_id = (call.data.get(ATTR_ENTRY_ID) or "").strip()
        entries = list(hass.config_entries.async_entries(DOMAIN))
        if entry_id:
            entries = [entry for entry in entries if entry.entry_id == entry_id]
            if not entries:
                raise HomeAssistantError(
                    f"Tesla EVTV BMS entry {entry_id!r} not found"
                )
        if not entries:
            raise HomeAssistantError("No Tesla EVTV BMS config entry found")
        for entry in entries:
            updates = webbox_data_updates(
                dict(entry.data),
                host=host,
                password=password,
            )
            if not updates:
                continue
            hass.config_entries.async_update_entry(
                entry, data={**dict(entry.data), **updates}
            )
            await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_WEBBOX,
        _handle_set_webbox,
        schema=SERVICE_SET_WEBBOX_SCHEMA,
    )
    return True



async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    name = entry.data["name"]
    port = entry.data["port"]
    name_lower = name.lower()

    hass.data.setdefault(DOMAIN, {})
    runtime = PackRuntime.from_entry_data(entry.data)
    hass.data[DOMAIN][name_lower] = runtime

    def udp_callback(sock):
        try:
            data, _ = sock.recvfrom(1024)
            parsed = parse_udp_packet(data, port)
            if not parsed:
                return
            async_dispatcher_send(
                hass,
                SIGNAL_UPDATE_ENTITY.format(name_lower),
                parsed,
            )
        except BlockingIOError:
            pass
        except OSError as e:
            _LOGGER.error("[%s] UDP read error on %s: %s", DOMAIN, name, e)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        loop.add_reader(sock.fileno(), udp_callback, sock)
        runtime.socket = sock
        runtime.loop = loop
        _LOGGER.info(
            "Started non-blocking UDP listener for %s on port %d (prefix=%s)",
            name,
            port,
            runtime.entity_prefix,
        )
    except OSError as e:
        _LOGGER.error("Failed to bind UDP socket on port %d for %s: %s", port, name, e)
        hass.data[DOMAIN].pop(name_lower, None)
        return False

    webbox_host = (entry.data.get(CONF_WEBBOX_HOST) or "").strip()
    if webbox_host:
        session = async_get_clientsession(hass)
        webbox_password = entry.data.get(CONF_WEBBOX_PASSWORD) or None
        scan_interval = int(
            entry.data.get(CONF_WEBBOX_SCAN_INTERVAL, DEFAULT_WEBBOX_SCAN_INTERVAL)
        )
        use_modbus = bool(entry.data.get(CONF_WEBBOX_MODBUS, DEFAULT_WEBBOX_MODBUS))
        modbus_port = int(
            entry.data.get(CONF_WEBBOX_MODBUS_PORT, DEFAULT_WEBBOX_MODBUS_PORT)
        )
        unit_gw = int(
            entry.data.get(CONF_WEBBOX_UNIT_GATEWAY, DEFAULT_WEBBOX_UNIT_GATEWAY)
        )
        unit_plant = int(
            entry.data.get(CONF_WEBBOX_UNIT_PLANT, DEFAULT_WEBBOX_UNIT_PLANT)
        )
        unit_dev = int(
            entry.data.get(CONF_WEBBOX_UNIT_DEVICE, DEFAULT_WEBBOX_UNIT_DEVICE)
        )
        runtime.webbox = {
            "host": webbox_host,
            "port": modbus_port,
            "modbus": use_modbus,
            "password": webbox_password,
            "unit_gateway": unit_gw,
            "unit_plant": unit_plant,
            "unit_device": unit_dev,
            "device_key": None,
        }
        fail_state = {"consecutive": 0, "last_warn": 0.0}
        poll_lock = asyncio.Lock()

        async def poll_webbox(now=None):
            # Overlapping 10s polls + 12s RPC retries wedge the WebBox TCP stack.
            if poll_lock.locked():
                _LOGGER.debug("[%s] WebBox poll still running for %s, skip", DOMAIN, webbox_host)
                return
            async with poll_lock:
                await _poll_webbox_locked()

        async def _poll_webbox_locked():
            values: dict = {}
            errors: list[str] = []

            # HTTP/RPC overview + GetParameter (GdManStr grid control)
            try:
                http_vals = await async_poll_webbox(
                    session, webbox_host, webbox_password
                )
                if http_vals:
                    values.update(http_vals)
                    # Cache SI device key for SetParameter writes
                    dk = http_vals.get("webbox_device_key")
                    if dk:
                        runtime.webbox["device_key"] = dk
            except Exception as e:  # noqa: BLE001
                errors.append(f"http:{e}")

            # Modbus TCP proxy (plant + SI parameters)
            if use_modbus:
                try:
                    mb_vals = await async_poll_webbox_modbus(
                        webbox_host,
                        port=modbus_port,
                        unit_gateway=unit_gw,
                        unit_plant=unit_plant,
                        unit_device=unit_dev,
                    )
                    if mb_vals:
                        # Prefer RPC GetParameter for grid control over Modbus 40527
                        values = merge_modbus_without_clobbering_rpc_params(
                            values, mb_vals
                        )
                except Exception as e:  # noqa: BLE001
                    errors.append(f"modbus:{e}")

            if errors and not values:
                fail_state["consecutive"] += 1
                t = time.monotonic()
                if fail_state["consecutive"] == 1 or (
                    t - fail_state["last_warn"]
                ) >= 300:
                    fail_state["last_warn"] = t
                    _LOGGER.warning(
                        "[%s] WebBox poll failed (%s) x%s: %s",
                        DOMAIN,
                        webbox_host,
                        fail_state["consecutive"],
                        "; ".join(errors),
                    )
                return

            if fail_state["consecutive"]:
                _LOGGER.info(
                    "[%s] WebBox %s reachable again after %s failures",
                    DOMAIN,
                    webbox_host,
                    fail_state["consecutive"],
                )
                fail_state["consecutive"] = 0

            if values:
                # kW mirror when HTTP-only power is present (Modbus path already sets it)
                if "webbox_power" in values and "webbox_power_kw" not in values:
                    try:
                        values["webbox_power_kw"] = round(
                            float(values["webbox_power"]) / 1000.0, 3
                        )
                    except (TypeError, ValueError):
                        pass
                async_dispatcher_send(
                    hass,
                    SIGNAL_UPDATE_ENTITY.format(name_lower),
                    values,
                )

        entry.async_on_unload(
            async_track_time_interval(
                hass, poll_webbox, timedelta(seconds=scan_interval)
            )
        )
        hass.async_create_task(poll_webbox())
        _LOGGER.info(
            "Started WebBox poller for %s at %s every %ds (modbus=%s port=%s)",
            name,
            webbox_host,
            scan_interval,
            use_modbus,
            modbus_port,
        )
    else:
        _LOGGER.info("WebBox host empty — solar/modbus poller disabled for %s", name)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    name_lower = entry.data["name"].lower()
    runtime = hass.data.get(DOMAIN, {}).get(name_lower)

    if isinstance(runtime, PackRuntime):
        sock = runtime.socket
        loop = runtime.loop
        if sock is not None:
            try:
                if loop is not None:
                    loop.remove_reader(sock.fileno())
            except Exception as e:
                _LOGGER.debug("remove_reader: %s", e)
            try:
                sock.close()
            except Exception as e:
                _LOGGER.debug("socket close: %s", e)
    elif runtime is not None:
        _LOGGER.error(
            "[%s] unload expected PackRuntime for %s, got %s",
            DOMAIN,
            name_lower,
            type(runtime).__name__,
        )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(name_lower, None)
    return unload_ok
