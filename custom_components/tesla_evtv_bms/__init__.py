import asyncio
import logging
import socket
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_WEBBOX_HOST,
    CONF_WEBBOX_PASSWORD,
    CONF_WEBBOX_SCAN_INTERVAL,
    DEFAULT_WEBBOX_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SIGNAL_UPDATE_ENTITY,
)
from .parser import parse_udp_packet
from .runtime import PackRuntime
from .webbox import async_poll_webbox

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
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
        scan_interval = entry.data.get(
            CONF_WEBBOX_SCAN_INTERVAL, DEFAULT_WEBBOX_SCAN_INTERVAL
        )
        webbox_fail_state = {"consecutive": 0, "last_warn": 0.0}

        async def poll_webbox(now=None):
            try:
                values = await async_poll_webbox(session, webbox_host, webbox_password)
            except Exception as e:
                webbox_fail_state["consecutive"] += 1
                t = time.monotonic()
                if webbox_fail_state["consecutive"] == 1 or (
                    t - webbox_fail_state["last_warn"]
                ) >= 300:
                    webbox_fail_state["last_warn"] = t
                    _LOGGER.warning(
                        "[%s] WebBox poll failed (%s) x%s: %s",
                        DOMAIN,
                        webbox_host,
                        webbox_fail_state["consecutive"],
                        e,
                    )
                return
            if webbox_fail_state["consecutive"]:
                _LOGGER.info(
                    "[%s] WebBox %s reachable again after %s failures",
                    DOMAIN,
                    webbox_host,
                    webbox_fail_state["consecutive"],
                )
                webbox_fail_state["consecutive"] = 0
            if values:
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
            "Started WebBox poller for %s at %s every %ds",
            name,
            webbox_host,
            scan_interval,
        )
    else:
        _LOGGER.info("WebBox host empty — solar poller disabled for %s", name)

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
