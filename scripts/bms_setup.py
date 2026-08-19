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


def _load_bms_flag() -> dict:
    if not BMS_FLAG.is_file():
        return {}
    try:
        data = json.loads(BMS_FLAG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_bms_flag(state: dict) -> None:
    try:
        BMS_FLAG.parent.mkdir(parents=True, exist_ok=True)
        BMS_FLAG.write_text(json.dumps(state) + "\n", encoding="utf-8")
    except OSError:
        pass


def _webbox_from_opts(opts: dict) -> dict:
    return {
        "webbox_host": str(opts.get("webbox_host") or "").strip(),
        "webbox_password": str(opts.get("webbox_password") or "").strip(),
    }


def _webbox_apply_needed(desired: dict, applied: dict) -> bool:
    """True when addon WebBox options should be written onto the BMS entry.

    Empty addon options never wipe a host the user set in the HA UI. A
    previously applied pair is skipped so addon restart does not reload
    the integration every time.
    """
    if not desired.get("webbox_host") and not desired.get("webbox_password"):
        return False
    return (
        str(desired.get("webbox_host") or "") != str(applied.get("webbox_host") or "")
        or str(desired.get("webbox_password") or "")
        != str(applied.get("webbox_password") or "")
    )


def _schema_defaults(flow: dict) -> dict:
    """Pull current-option defaults from an options-flow form schema."""
    out: dict = {}
    for field in flow.get("data_schema") or []:
        if isinstance(field, dict) and "name" in field and "default" in field:
            out[str(field["name"])] = field["default"]
    return out


def _remember_webbox_applied(opts: dict) -> None:
    desired = _webbox_from_opts(opts)
    if not desired.get("webbox_host") and not desired.get("webbox_password"):
        return
    state = _load_bms_flag()
    state["webbox_applied"] = desired
    _save_bms_flag(state)


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
    """True when Core can start a tesla_evtv_bms config flow.

    Config-flow integrations do not appear in /api/components until an
    entry exists, so we must not use that list (it caused restart loops).
    """
    try:
        handlers = _ha_api("/config/config_entries/flow_handlers", token=token)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
    ):
        return False
    if not isinstance(handlers, list):
        return False
    return "tesla_evtv_bms" in handlers


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
        _remember_webbox_applied(opts)
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
    state = _load_bms_flag()
    last = float(state.get("restart_requested_at") or 0)
    if last and (now - last) < 600:
        return "Core restart already requested; waiting for tesla_evtv_bms to load"
    try:
        _ha_api(
            "/services/homeassistant/restart",
            token=token,
            method="POST",
            body={},
            timeout=3,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        # restart drops the proxy; treat timeout as "restart kicked off"
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            pass
        else:
            return f"could not restart Core: {exc}"
    state["restart_requested_at"] = now
    _save_bms_flag(state)
    return "requested Core restart so tesla_evtv_bms can load"


def _find_bms_entry(token: str) -> dict | None:
    try:
        entries = _ha_api("/config/config_entries/entry", token=token)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
    ):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("domain") == "tesla_evtv_bms":
            return entry
    return None


def _apply_webbox_via_options_flow(
    token: str, entry_id: str, desired: dict
) -> str:
    """Write WebBox host/password onto an existing BMS entry (options flow)."""
    try:
        start = _ha_api(
            "/config/config_entries/options/flow",
            token=token,
            method="POST",
            body={"handler": entry_id},
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
        return f"WebBox options flow start failed HTTP {exc.code}: {body[:200]}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"WebBox options flow start failed: {exc}"

    if not isinstance(start, dict):
        return f"WebBox options flow start: unexpected response {start!r}"
    if start.get("type") == "abort":
        return f"WebBox options flow abort: {start.get('reason') or 'unknown'}"
    flow_id = start.get("flow_id")
    if not flow_id:
        return f"WebBox options flow missing flow_id: {start}"

    payload = _schema_defaults(start)
    if desired.get("webbox_host"):
        payload["webbox_host"] = desired["webbox_host"]
    if desired.get("webbox_password"):
        payload["webbox_password"] = desired["webbox_password"]

    try:
        result = _ha_api(
            f"/config/config_entries/options/flow/{flow_id}",
            token=token,
            method="POST",
            body=payload,
            timeout=60,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
        return f"WebBox options flow submit failed HTTP {exc.code}: {body[:200]}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"WebBox options flow submit failed: {exc}"

    if isinstance(result, dict) and result.get("type") == "create_entry":
        host = desired.get("webbox_host") or "(password only)"
        return f"applied WebBox {host} to Tesla EVTV BMS"
    return f"WebBox options flow unfinished: {result}"


def _sync_webbox_on_existing_entry(opts: dict, token: str) -> str | None:
    """Apply addon WebBox options to a BMS entry that was created without them."""
    desired = _webbox_from_opts(opts)
    applied = _load_bms_flag().get("webbox_applied")
    if not isinstance(applied, dict):
        applied = {}
    if not _webbox_apply_needed(desired, applied):
        return None
    entry = _find_bms_entry(token)
    if not entry or not entry.get("entry_id"):
        return "WebBox sync skipped (no tesla_evtv_bms entry id)"
    msg = _apply_webbox_via_options_flow(token, str(entry["entry_id"]), desired)
    if msg.startswith("applied WebBox"):
        _remember_webbox_applied(opts)
    return msg


def _ensure_bms_entry(opts: dict, *, wait: bool = False) -> list[str]:
    """Create the Tesla EVTV BMS config entry when missing.

    If the entry already exists, still push addon ``webbox_host`` /
    ``webbox_password`` onto it — auto-setup used to create the entry once
    with an empty host and never update it, which left WebBox sensors dead.
    """
    token = _ha_token(opts)
    if not bool(opts.get("auto_setup_bms", True)):
        msgs = ["auto_setup_bms disabled"]
        if token:
            bat = _apply_bat_typ_oneshot(opts, token)
            if bat:
                msgs.append(bat)
        return msgs
    if not token:
        return ["skip BMS setup (no SUPERVISOR_TOKEN / ha_token)"]

    prefix = str(opts.get("pack_prefix") or "battery_storage_tesla_pack").strip()
    deadline = time.monotonic() + (180 if wait else 0)
    last = ""
    while True:
        if _bms_already_configured(token, prefix):
            msgs = ["Tesla EVTV BMS already configured"]
            sync = _sync_webbox_on_existing_entry(opts, token)
            if sync:
                msgs.append(sync)
            bat = _apply_bat_typ_oneshot(opts, token)
            if bat:
                msgs.append(bat)
            return msgs
        if _bms_component_loaded(token):
            created = _create_bms_config_entry(opts, token)
            msgs = [created]
            bat = _apply_bat_typ_oneshot(opts, token)
            if bat:
                msgs.append(bat)
            return msgs
        last = _request_core_restart(token)
        if not wait or time.monotonic() >= deadline:
            return [last]
        time.sleep(5)


BAT_TYP_LIION_EXT_BMS = "LiIon_Ext-BMS"


def _bat_typ_already_liion(state: str | None) -> bool:
    """True when a HA sensor state already reads official LiIon_Ext-BMS."""
    if state is None:
        return False
    raw = str(state).strip()
    if not raw or raw.lower() in ("unknown", "unavailable", "none", "—", "-"):
        return False
    key = raw.lower().replace(" ", "_").replace("-", "_")
    return key in (
        "liion_ext_bms",
        "liion_extbms",
        "liion",
        "lithium",
        "lithium_ext_bms",
    ) or raw == BAT_TYP_LIION_EXT_BMS


def _bat_typ_oneshot_needed(opts: dict, flag: dict) -> bool:
    """One-shot installer hook: default off; skip if already applied or no WebBox."""
    if not bool(opts.get("apply_bat_typ_liion_ext_bms", False)):
        return False
    if not str(opts.get("webbox_host") or "").strip():
        return False
    return not bool(flag.get("bat_typ_applied"))


def _remember_bat_typ_applied() -> None:
    state = _load_bms_flag()
    state["bat_typ_applied"] = BAT_TYP_LIION_EXT_BMS
    _save_bms_flag(state)


def _apply_bat_typ_oneshot(opts: dict, token: str) -> str | None:
    """Write BatTyp=LiIon_Ext-BMS once via set_si_parameter if not already set."""
    flag = _load_bms_flag()
    if not _bat_typ_oneshot_needed(opts, flag):
        return None
    prefix = str(opts.get("pack_prefix") or "battery_storage_tesla_pack").strip()
    eid = f"sensor.{prefix}_webbox_bat_typ"
    current = None
    try:
        st = _ha_api(f"/states/{eid}", token=token)
        if isinstance(st, dict):
            current = st.get("state")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return f"BatTyp oneshot state read failed HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"BatTyp oneshot state read failed: {exc}"

    if _bat_typ_already_liion(current if isinstance(current, str) else None):
        _remember_bat_typ_applied()
        return f"BatTyp already {BAT_TYP_LIION_EXT_BMS} — skip write"

    try:
        _ha_api(
            "/services/tesla_evtv_bms/set_si_parameter",
            token=token,
            method="POST",
            body={
                "parameter": "bat_typ",
                "value": BAT_TYP_LIION_EXT_BMS,
                "entity_prefix": prefix,
            },
            timeout=30,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
        return f"BatTyp oneshot write failed HTTP {exc.code}: {body[:200]}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"BatTyp oneshot write failed: {exc}"

    _remember_bat_typ_applied()
    return f"applied BatTyp={BAT_TYP_LIION_EXT_BMS} via set_si_parameter"


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
        "apply_bat_typ_liion_ext_bms": False,
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
    try:
        print(f"[sunny_island] {_ensure_packages_include()}")
    except OSError as exc:
        print(f"[sunny_island] WARN: packages include failed: {exc}")
    opts = _load_options()
    for msg in _ensure_bms_entry(opts, wait=True):
        print(f"[sunny_island] {msg}")
    return 0


if __name__ == "__main__":
    if "--ensure-bms" in sys.argv:
        raise SystemExit(_ensure_bms_cli())
    raise SystemExit("usage: bms_setup.py --ensure-bms")
