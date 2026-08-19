#!/usr/bin/env python3
"""Tesla EVTV BMS config-entry setup + configuration.yaml packages include."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HA_CONFIG = Path(os.environ.get("SI_HA_CONFIG", "/config"))
OPTIONS_PATH = Path(os.environ.get("SI_OPTIONS", "/data/options.json"))
BMS_FLAG = Path(os.environ.get("SI_BMS_FLAG", "/data/bms_setup.json"))


def _ha_token(opts: dict | None = None) -> str:
    tok = (
        os.environ.get("SUPERVISOR_TOKEN")
        or os.environ.get("HASSIO_TOKEN")
        or ""
    ).strip()
    if tok:
        return tok
    if opts:
        return str(opts.get("ha_token") or "").strip()
    return ""


def _ha_api(
    path: str,
    *,
    token: str,
    method: str = "GET",
    body: dict | None = None,
    timeout: float = 15,
):
    """Call Home Assistant Core via Supervisor proxy."""
    url = f"http://supervisor/core/api{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if not raw:
            return None
        return json.loads(raw.decode())


def _ensure_packages_include() -> str:
    """Add homeassistant.packages include when missing. Surgical; no other edits."""
    cfg = HA_CONFIG / "configuration.yaml"
    if not cfg.is_file():
        return "configuration.yaml missing — skipped packages include"
    text = cfg.read_text(encoding="utf-8")
    if "include_dir_named packages" in text:
        return "packages include already present"

    import re

    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if re.match(r"^homeassistant:\s*(#.*)?$", line):
            lines.insert(i + 1, "  packages: !include_dir_named packages\n")
            cfg.write_text("".join(lines), encoding="utf-8")
            return "added packages: under existing homeassistant: block"

    block = (
        "\n# Sunny Island — load /config/packages (helpers + plant YAML)\n"
        "homeassistant:\n"
        "  packages: !include_dir_named packages\n"
    )
    if text and not text.endswith("\n"):
        text += "\n"
    cfg.write_text(text + block, encoding="utf-8")
    return "added homeassistant.packages include to configuration.yaml"


def _bms_flow_payload(opts: dict) -> dict:
    """Config-flow user-step payload for Tesla EVTV BMS."""
    prefix = str(opts.get("pack_prefix") or "battery_storage_tesla_pack").strip()
    try:
        port = int(opts.get("bms_udp_port") or 6550)
    except (TypeError, ValueError):
        port = 6550
    return {
        "name": "Tesla Pack",
        "port": port,
        "entity_prefix": prefix,
        "pack_size": 75.0,
        "cells_in_series": 12,
        "min_cell_volts": 3.2,
        "max_cell_volts": 4.1,
        "webbox_host": str(opts.get("webbox_host") or "").strip(),
        "webbox_password": str(opts.get("webbox_password") or "").strip(),
        "webbox_scan_interval": 10,
        "webbox_modbus": True,
        "webbox_modbus_port": 502,
        "webbox_unit_gateway": 1,
        "webbox_unit_plant": 2,
        "webbox_unit_device": 3,
    }


def _bms_component_loaded(token: str) -> bool:
    try:
        components = _ha_api("/components", token=token)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
    ):
        return False
    if not isinstance(components, list):
        return False
    return any(
        str(c) == "tesla_evtv_bms" or str(c).startswith("tesla_evtv_bms.")
        for c in components
    )


def _bms_already_configured(token: str, prefix: str) -> bool:
    eid = f"sensor.{prefix}_volts"
    try:
        st = _ha_api(f"/states/{eid}", token=token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        return False
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False
    return isinstance(st, dict) and st.get("entity_id") == eid


def _create_bms_config_entry(opts: dict, token: str) -> str:
    payload = _bms_flow_payload(opts)
    try:
        start = _ha_api(
            "/config/config_entries/flow",
            token=token,
            method="POST",
            body={"handler": "tesla_evtv_bms", "show_advanced_options": True},
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
        return f"BMS flow start failed HTTP {exc.code}: {body[:200]}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"BMS flow start failed: {exc}"

    if not isinstance(start, dict):
        return f"BMS flow start: unexpected response {start!r}"
    if start.get("type") == "abort":
        reason = start.get("reason") or "unknown"
        if reason in ("already_configured", "already_in_progress"):
            return f"BMS already configured ({reason})"
        return f"BMS flow abort: {reason}"

    flow_id = start.get("flow_id")
    if not flow_id:
        return f"BMS flow start missing flow_id: {start}"

    try:
        result = _ha_api(
            f"/config/config_entries/flow/{flow_id}",
            token=token,
            method="POST",
            body=payload,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
        return f"BMS flow submit failed HTTP {exc.code}: {body[:200]}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"BMS flow submit failed: {exc}"

    if isinstance(result, dict) and result.get("type") == "create_entry":
        return (
            f"created Tesla EVTV BMS entry "
            f"{result.get('title') or payload['name']} "
            f"udp={payload['port']} prefix={payload['entity_prefix']}"
        )
    if isinstance(result, dict) and result.get("type") == "abort":
        reason = result.get("reason") or "unknown"
        if reason in ("already_configured", "already_in_progress"):
            return f"BMS already configured ({reason})"
        return f"BMS flow abort: {reason}"
    return f"BMS flow unfinished: {result}"


def _request_core_restart(token: str) -> str:
    now = time.time()
    state: dict = {}
    if BMS_FLAG.is_file():
        try:
            state = json.loads(BMS_FLAG.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    last = float(state.get("restart_requested_at") or 0)
    if last and (now - last) < 600:
        return "Core restart already requested; waiting for tesla_evtv_bms to load"
    try:
        _ha_api(
            "/services/homeassistant/restart",
            token=token,
            method="POST",
            body={},
            timeout=8,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return f"could not restart Core: {exc}"
    state["restart_requested_at"] = now
    try:
        BMS_FLAG.parent.mkdir(parents=True, exist_ok=True)
        BMS_FLAG.write_text(json.dumps(state) + "\n", encoding="utf-8")
    except OSError:
        pass
    return "requested Core restart so tesla_evtv_bms can load"


def _ensure_bms_entry(opts: dict, *, wait: bool = False) -> list[str]:
    """Create the Tesla EVTV BMS config entry when missing."""
    if not bool(opts.get("auto_setup_bms", True)):
        return ["auto_setup_bms disabled"]
    token = _ha_token(opts)
    if not token:
        return ["skip BMS setup (no SUPERVISOR_TOKEN / ha_token)"]

    prefix = str(opts.get("pack_prefix") or "battery_storage_tesla_pack").strip()
    deadline = time.monotonic() + (180 if wait else 0)
    last = ""
    while True:
        if _bms_already_configured(token, prefix):
            return ["Tesla EVTV BMS already configured"]
        if _bms_component_loaded(token):
            return [_create_bms_config_entry(opts, token)]
        last = _request_core_restart(token)
        if not wait or time.monotonic() >= deadline:
            return [last]
        time.sleep(5)


def _load_options() -> dict:
    defaults = {
        "auto_sync": True,
        "install_dashboard": True,
        "force_overwrite": False,
        "log_level": "info",
        "auto_setup_bms": True,
        "bms_udp_port": 6550,
        "webbox_host": "",
        "webbox_password": "",
        "pack_prefix": "battery_storage_tesla_pack",
        "ha_token": "",
    }
    if not OPTIONS_PATH.is_file():
        return defaults
    try:
        opts = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        return {**defaults, **opts}
    except (OSError, json.JSONDecodeError):
        return defaults


def _ensure_bms_cli() -> int:
    """Background: wait for Core, then create Tesla EVTV BMS entry."""
    opts = _load_options()
    for msg in _ensure_bms_entry(opts, wait=True):
        print(f"[sunny_island] {msg}")
    return 0


if __name__ == "__main__":
    if "--ensure-bms" in sys.argv:
        raise SystemExit(_ensure_bms_cli())
    raise SystemExit("usage: bms_setup.py --ensure-bms")
