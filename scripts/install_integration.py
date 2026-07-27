#!/usr/bin/env python3
"""Install / sync Tesla EVTV BMS custom component into HA /config."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

OPTIONS_PATH = Path(os.environ.get("SI_OPTIONS", "/data/options.json"))
STATUS_PATH = Path(os.environ.get("SI_STATUS_OUT", "/data/status.json"))
HA_CONFIG = Path(os.environ.get("SI_HA_CONFIG", "/config"))
BUNDLE = Path(os.environ.get("SI_BUNDLE", "/opt/sunny_island"))

SRC_CC = BUNDLE / "custom_components" / "tesla_evtv_bms"
DST_CC = HA_CONFIG / "custom_components" / "tesla_evtv_bms"
SRC_DASH = BUNDLE / "dashboards"
DST_DASH = HA_CONFIG / "dashboards" / "sunny_island"
SRC_EXAMPLES = BUNDLE / "ha_config"
DST_EXAMPLES = HA_CONFIG / "sunny_island_examples"

APP_VERSION = "2.0.0"


def _load_options() -> dict:
    defaults = {
        "auto_sync": True,
        "install_dashboard": True,
        "force_overwrite": True,
        "log_level": "info",
    }
    if not OPTIONS_PATH.is_file():
        return defaults
    try:
        opts = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        return {**defaults, **opts}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[sunny_island] options parse failed: {exc}")
        return defaults


def _manifest_version(path: Path) -> str | None:
    mf = path / "manifest.json"
    if not mf.is_file():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8")).get("version")
    except (OSError, json.JSONDecodeError):
        return None


def _copy_tree(src: Path, dst: Path, *, force: bool) -> str:
    if not src.is_dir():
        return f"missing source {src}"
    if dst.exists() and not force:
        return f"skipped (exists, force_overwrite=false): {dst}"
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    return f"installed {src.name} → {dst}"


def main() -> int:
    opts = _load_options()
    auto_sync = bool(opts.get("auto_sync", True))
    install_dashboard = bool(opts.get("install_dashboard", True))
    force = bool(opts.get("force_overwrite", True))

    actions: list[str] = []
    errors: list[str] = []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if not HA_CONFIG.is_dir():
        errors.append(f"HA config not mounted at {HA_CONFIG} (need map: config:rw)")
        print(f"[sunny_island] ERROR: {errors[-1]}")
    elif auto_sync:
        try:
            msg = _copy_tree(SRC_CC, DST_CC, force=force)
            actions.append(msg)
            print(f"[sunny_island] {msg}")
            ver = _manifest_version(DST_CC)
            if ver:
                actions.append(f"integration version {ver}")
                print(f"[sunny_island] BMS integration version {ver}")
        except OSError as exc:
            errors.append(f"integration sync failed: {exc}")
            print(f"[sunny_island] ERROR: {errors[-1]}")

        if install_dashboard and SRC_DASH.is_dir():
            try:
                msg = _copy_tree(SRC_DASH, DST_DASH, force=force)
                actions.append(msg)
                print(f"[sunny_island] {msg}")
            except OSError as exc:
                errors.append(f"dashboard sync failed: {exc}")
                print(f"[sunny_island] ERROR: {errors[-1]}")

        if SRC_EXAMPLES.is_dir():
            try:
                msg = _copy_tree(SRC_EXAMPLES, DST_EXAMPLES, force=True)
                actions.append(msg)
                print(f"[sunny_island] {msg}")
            except OSError as exc:
                errors.append(f"examples sync failed: {exc}")
                print(f"[sunny_island] ERROR: {errors[-1]}")
    else:
        actions.append("auto_sync disabled — no files copied")
        print("[sunny_island] auto_sync=false")

    status = {
        "name": "Sunny Island",
        "addon_version": APP_VERSION,
        "integration_version": _manifest_version(DST_CC) or _manifest_version(SRC_CC),
        "synced_at": now,
        "ha_config": str(HA_CONFIG),
        "installed_path": str(DST_CC) if DST_CC.is_dir() else None,
        "auto_sync": auto_sync,
        "install_dashboard": install_dashboard,
        "actions": actions,
        "errors": errors,
        "ok": not errors and DST_CC.is_dir(),
        "next_steps": [
            "Open sidebar → Sunny Island for live plant UI",
            "Settings → Devices & services → Tesla EVTV BMS (add if missing)",
            "UDP port default 6550 · cells_in_series 12 for 2-line 12S",
            "Restart HA Core after integration updates",
            "Examples: /config/sunny_island_examples/",
        ],
    }

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

    # Expose for optional UI /debug
    try:
        (BUNDLE / "www" / "status.json").write_text(
            json.dumps(status, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass

    print(f"[sunny_island] status written → {STATUS_PATH}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
