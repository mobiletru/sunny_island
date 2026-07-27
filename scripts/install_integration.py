#!/usr/bin/env python3
"""Install / sync Tesla EVTV BMS + Lovelace dashboards into HA /config."""

from __future__ import annotations

import json
import os
import re
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
DST_DASH_DIR = HA_CONFIG / "dashboards" / "sunny_island"
DST_DASH_ROOT = HA_CONFIG / "dashboards"
SRC_EXAMPLES = BUNDLE / "ha_config"
DST_EXAMPLES = HA_CONFIG / "sunny_island_examples"
CONFIGURATION = HA_CONFIG / "configuration.yaml"

APP_VERSION = "2.1.0"

# Lovelace dashboards registered in configuration.yaml
# Paths are relative to /config
LOVELACE_DASHBOARDS = {
    "lovelace": {
        "mode": "yaml",
        "filename": "dashboards/webbox.yaml",
        "title": "Sunny Island",
        "icon": "mdi:solar-power-variant",
        "show_in_sidebar": True,
    },
    "sunny-island-detail": {
        "mode": "yaml",
        "filename": "dashboards/webbox.yaml",
        "title": "Sunny Island detail",
        "icon": "mdi:solar-power-variant",
        "show_in_sidebar": True,
    },
    "sunny-island-pack": {
        "mode": "yaml",
        "filename": "dashboards/sunny_island/sunny_island_detail.yaml",
        "title": "Pack detail",
        "icon": "mdi:car-battery",
        "show_in_sidebar": True,
    },
    "sunny-island-webbox": {
        "mode": "yaml",
        "filename": "dashboards/sunny_island/ha_webbox_dashboard.yaml",
        "title": "WebBox plant",
        "icon": "mdi:solar-panel-large",
        "show_in_sidebar": True,
    },
}

# Files copied from bundle dashboards/ into /config/dashboards/
# (root copies keep existing public URLs working)
ROOT_DASHBOARD_COPIES = {
    "webbox.yaml": "webbox.yaml",
    "plant.yaml": "plant.yaml",
}


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


def _copy_file(src: Path, dst: Path, *, force: bool) -> str:
    if not src.is_file():
        return f"missing file {src}"
    if dst.exists() and not force:
        return f"skipped file (exists): {dst}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return f"copied {src.name} → {dst}"


def _yaml_bool(v: bool) -> str:
    return "true" if v else "false"


def _dashboard_block() -> str:
    lines = [
        "lovelace:",
        "  resource_mode: yaml",
        "  dashboards:",
    ]
    for slug, cfg in LOVELACE_DASHBOARDS.items():
        lines.append(f"    {slug}:")
        lines.append(f"      mode: {cfg['mode']}")
        lines.append(f"      filename: {cfg['filename']}")
        lines.append(f"      title: {cfg['title']}")
        lines.append(f"      icon: {cfg['icon']}")
        lines.append(f"      show_in_sidebar: {_yaml_bool(bool(cfg['show_in_sidebar']))}")
    return "\n".join(lines) + "\n"


def _ensure_lovelace_dashboards() -> str:
    """Merge/replace lovelace.dashboards in configuration.yaml so HA loads our YAML dashboards."""
    if not CONFIGURATION.is_file():
        return f"configuration.yaml missing at {CONFIGURATION}"

    text = CONFIGURATION.read_text(encoding="utf-8")
    block = _dashboard_block()

    # Replace existing lovelace: top-level block (until next top-level key or EOF)
    pattern = re.compile(
        r"(?ms)^lovelace:\n(?:[ \t]+.*\n)*",
    )
    if pattern.search(text):
        new_text = pattern.sub(block, text, count=1)
        action = "updated lovelace dashboards in configuration.yaml"
    else:
        # Append before http: if present, else at end
        http_m = re.search(r"(?m)^http:\s*$", text)
        if http_m:
            new_text = text[: http_m.start()] + "\n" + block + "\n" + text[http_m.start() :]
        else:
            new_text = text.rstrip() + "\n\n" + block
        action = "added lovelace dashboards to configuration.yaml"

    if new_text != text:
        CONFIGURATION.write_text(new_text, encoding="utf-8")
        return action
    return "lovelace dashboards already current"


def _install_dashboards(*, force: bool) -> list[str]:
    actions: list[str] = []
    if not SRC_DASH.is_dir():
        actions.append(f"missing dashboards bundle {SRC_DASH}")
        return actions

    # Full tree under /config/dashboards/sunny_island/
    actions.append(_copy_tree(SRC_DASH, DST_DASH_DIR, force=force))

    # Root copies for public URLs used by configuration.yaml
    for src_name, dst_name in ROOT_DASHBOARD_COPIES.items():
        src = SRC_DASH / src_name
        # Prefer plant.yaml as webbox.yaml if webbox missing
        if not src.is_file() and src_name == "webbox.yaml":
            src = SRC_DASH / "plant.yaml"
        if src.is_file():
            actions.append(_copy_file(src, DST_DASH_ROOT / dst_name, force=True))

    # Also mirror detail into root for convenience
    detail = SRC_DASH / "sunny_island_detail.yaml"
    if detail.is_file():
        actions.append(
            _copy_file(detail, DST_DASH_ROOT / "sunny_island_detail.yaml", force=True)
        )

    try:
        actions.append(_ensure_lovelace_dashboards())
    except OSError as exc:
        actions.append(f"lovelace register failed: {exc}")

    return actions


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

        if install_dashboard:
            try:
                for msg in _install_dashboards(force=force):
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
        "dashboards": {
            "dir": str(DST_DASH_DIR) if DST_DASH_DIR.is_dir() else None,
            "registered": list(LOVELACE_DASHBOARDS.keys()),
            "files": sorted(p.name for p in DST_DASH_DIR.glob("*.yaml"))
            if DST_DASH_DIR.is_dir()
            else [],
        },
        "auto_sync": auto_sync,
        "install_dashboard": install_dashboard,
        "actions": actions,
        "errors": errors,
        "ok": not errors and DST_CC.is_dir(),
        "next_steps": [
            "Sidebar: Sunny Island · Pack detail · WebBox plant",
            "Public URL: /sunny-island-detail/overview",
            "Settings → Devices & services → Tesla EVTV BMS (if missing)",
            "Reload Lovelace or restart HA Core after dashboard updates",
            "Examples: /config/sunny_island_examples/",
        ],
    }

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

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
