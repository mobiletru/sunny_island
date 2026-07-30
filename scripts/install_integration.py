#!/usr/bin/env python3
"""Install / sync Tesla EVTV BMS + Lovelace dashboards into HA /config.

Does NOT rewrite configuration.yaml. Writes a ready-to-include snippet and
status.json so the operator (or docs) can wire dashboards once.

Integration tree is updated when:
  - force_overwrite is true, or
  - destination is missing, or
  - installed manifest version differs from the bundle version
"""

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
DST_DASH_DIR = HA_CONFIG / "dashboards" / "sunny_island"
SRC_EXAMPLES = BUNDLE / "ha_config"
DST_EXAMPLES = HA_CONFIG / "sunny_island_examples"
SRC_PACKAGES = BUNDLE / "ha_config" / "packages"
DST_PACKAGES = HA_CONFIG / "packages"
SNIPPET_PATH = DST_DASH_DIR / "lovelace_include.yaml"
README_PATH = DST_DASH_DIR / "README.md"
ADDON_CONFIG = BUNDLE.parent / "config.yaml"  # /opt/sunny_island/../config.yaml may not exist in image

# App-owned package files always kept in sync with the bundle (content-gated).
APP_PACKAGE_FILES = (
    "sunny_island.yaml",
    "webbox_modbus.yaml",
)


def _app_version() -> str:
    """Single version source: SI_APP_VERSION env, else config.yaml beside bundle, else manifest label."""
    env = os.environ.get("SI_APP_VERSION", "").strip()
    if env:
        return env
    # In the image, config.yaml is not copied; Dockerfile ARG is not available.
    # Prefer a version file we can ship, or fall back to reading /addons path when present.
    for candidate in (
        BUNDLE / "APP_VERSION",
        Path("/addons/sunny_island/config.yaml"),
        Path(__file__).resolve().parents[1] / "config.yaml",
    ):
        if not candidate.is_file():
            continue
        if candidate.name == "APP_VERSION":
            return candidate.read_text(encoding="utf-8").strip() or "0.0.0"
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


LOVELACE_DASHBOARDS = {
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


def _load_options() -> dict:
    defaults = {
        "auto_sync": True,
        "install_dashboard": True,
        "force_overwrite": False,
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


def _should_sync_tree(src: Path, dst: Path, *, force: bool) -> tuple[bool, str]:
    """Decide whether to replace dst with src. Prefer version-gated upgrades."""
    if not src.is_dir():
        return False, f"missing source {src}"
    if force:
        return True, "force_overwrite"
    if not dst.exists():
        return True, "missing destination"
    src_ver = _manifest_version(src)
    dst_ver = _manifest_version(dst)
    if src_ver and dst_ver and src_ver != dst_ver:
        return True, f"version upgrade {dst_ver} → {src_ver}"
    if src_ver and not dst_ver:
        return True, f"missing dest version; install {src_ver}"
    return False, f"skipped (exists, version={dst_ver or 'unknown'}, force_overwrite=false)"


def _copy_tree(src: Path, dst: Path, *, force: bool) -> str:
    ok, reason = _should_sync_tree(src, dst, force=force)
    if not ok:
        if reason.startswith("missing source"):
            return reason
        return reason
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    ver = _manifest_version(dst)
    return f"installed {src.name} → {dst} ({reason}" + (f", v{ver})" if ver else ")")


def _copy_file(src: Path, dst: Path, *, force: bool) -> str:
    if not src.is_file():
        return f"missing file {src}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    new = src.read_bytes()
    if dst.is_file():
        if not force and dst.read_bytes() == new:
            return f"dashboard current: {dst.name}"
        if not force and dst.read_bytes() != new:
            # App-owned dashboards: still update when content changed in the bundle
            dst.write_bytes(new)
            return f"updated {src.name} → {dst}"
    else:
        dst.write_bytes(new)
        return f"copied {src.name} → {dst}"
    dst.write_bytes(new)
    return f"copied {src.name} → {dst} (force)"


def _yaml_bool(v: bool) -> str:
    return "true" if v else "false"


def _dashboard_snippet() -> str:
    lines = [
        "# Generated by Sunny Island add-on — do not hand-edit; re-sync overwrites.",
        "# Merge under configuration.yaml:",
        "#",
        "# lovelace:",
        "#   mode: storage   # or yaml",
        "#   dashboards:",
        "#     !include dashboards/sunny_island/lovelace_include.yaml",
        "#",
        "# Or copy the keys below into lovelace.dashboards manually.",
        "",
    ]
    for slug, cfg in LOVELACE_DASHBOARDS.items():
        lines.append(f"{slug}:")
        lines.append(f"  mode: {cfg['mode']}")
        lines.append(f"  filename: {cfg['filename']}")
        lines.append(f"  title: {cfg['title']}")
        lines.append(f"  icon: {cfg['icon']}")
        lines.append(f"  show_in_sidebar: {_yaml_bool(bool(cfg['show_in_sidebar']))}")
    return "\n".join(lines) + "\n"


def _dashboard_readme() -> str:
    return (
        "# Sunny Island Lovelace dashboards\n\n"
        "YAML dashboards live in this folder. The add-on does **not** rewrite "
        "`configuration.yaml`.\n\n"
        "To register sidebars, merge the contents of `lovelace_include.yaml` "
        "under `lovelace.dashboards` (or open the YAML files via a manual "
        "dashboard).\n\n"
        "Files:\n"
        "- `sunny_island_detail.yaml` — pack detail\n"
        "- `ha_webbox_dashboard.yaml` — WebBox plant\n"
    )


def _write_dashboard_helpers(*, force: bool) -> list[str]:
    actions: list[str] = []
    DST_DASH_DIR.mkdir(parents=True, exist_ok=True)
    snippet = _dashboard_snippet()
    if SNIPPET_PATH.is_file() and not force:
        if SNIPPET_PATH.read_text(encoding="utf-8") == snippet:
            actions.append("lovelace snippet already current")
        else:
            actions.append("skipped lovelace snippet (exists, force_overwrite=false)")
    else:
        SNIPPET_PATH.write_text(snippet, encoding="utf-8")
        actions.append(f"wrote {SNIPPET_PATH}")
    if README_PATH.is_file() and not force:
        actions.append("skipped dashboards README (exists)")
    else:
        README_PATH.write_text(_dashboard_readme(), encoding="utf-8")
        actions.append(f"wrote {README_PATH}")
    return actions


def _install_dashboards(*, force: bool) -> list[str]:
    actions: list[str] = []
    if not SRC_DASH.is_dir():
        actions.append(f"missing dashboards bundle {SRC_DASH}")
        return actions

    DST_DASH_DIR.mkdir(parents=True, exist_ok=True)
    for src in sorted(SRC_DASH.glob("*.yaml")):
        actions.append(_copy_file(src, DST_DASH_DIR / src.name, force=force))

    detail = SRC_DASH / "sunny_island_detail.yaml"
    if detail.is_file():
        root_detail = HA_CONFIG / "dashboards" / "sunny_island_detail.yaml"
        actions.append(_copy_file(detail, root_detail, force=force))

    try:
        actions.extend(_write_dashboard_helpers(force=force))
    except OSError as exc:
        actions.append(f"dashboard helpers failed: {exc}")

    return actions


def _copy_if_changed(src: Path, dst: Path) -> str:
    """Copy when missing or content differs (app-owned files)."""
    if not src.is_file():
        return f"missing file {src}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    new = src.read_bytes()
    if dst.is_file() and dst.read_bytes() == new:
        return f"package current: {dst.name}"
    dst.write_bytes(new)
    return f"installed package {src.name} → {dst}"


def _install_packages() -> list[str]:
    """Sync ha_config/packages into /config/packages (WebBox Modbus, helpers)."""
    actions: list[str] = []
    if not SRC_PACKAGES.is_dir():
        actions.append(f"missing packages bundle {SRC_PACKAGES}")
        return actions
    DST_PACKAGES.mkdir(parents=True, exist_ok=True)
    for name in APP_PACKAGE_FILES:
        src = SRC_PACKAGES / name
        if src.is_file():
            actions.append(_copy_if_changed(src, DST_PACKAGES / name))
    # Any extra package yaml shipped later
    for src in sorted(SRC_PACKAGES.glob("*.yaml")):
        if src.name not in APP_PACKAGE_FILES:
            actions.append(_copy_if_changed(src, DST_PACKAGES / src.name))
    # Reminder note (never rewrite configuration.yaml)
    note = DST_PACKAGES / "README_sunny_island.txt"
    note_body = (
        "Sunny Island packages (managed by the add-on).\n"
        "Ensure configuration.yaml has:\n"
        "  homeassistant:\n"
        "    packages: !include_dir_named packages\n"
        "Set secrets.webbox_host (and optional webbox_password) for Modbus/RPC.\n"
        "See sunny_island_examples/ or ha_config/secrets.example.yaml.\n"
    )
    if not note.is_file() or note.read_text(encoding="utf-8") != note_body:
        note.write_text(note_body, encoding="utf-8")
        actions.append(f"wrote {note}")
    return actions


def _install_scripts_automations(*, force: bool) -> list[str]:
    """Install car-charger / protection / auto-amps YAML into /config when empty or force.

    Does not clobber non-empty user scripts/automations unless force_overwrite.
    """
    actions: list[str] = []
    pairs = [
        (SRC_EXAMPLES / "scripts.car_charger.yaml", "scripts"),
        (SRC_EXAMPLES / "scripts.tessie_auto_amps.yaml", "scripts"),
        (SRC_EXAMPLES / "automations.pack_protection.yaml", "automations"),
        (SRC_EXAMPLES / "automations.tessie_auto_amps.yaml", "automations"),
    ]
    script_parts: list[str] = []
    auto_parts: list[str] = []
    for src, kind in pairs:
        if not src.is_file():
            actions.append(f"missing {src.name}")
            continue
        body = src.read_text(encoding="utf-8").rstrip() + "\n"
        if kind == "scripts":
            script_parts.append(body)
        else:
            auto_parts.append(body)

    scripts_dst = HA_CONFIG / "scripts.yaml"
    autos_dst = HA_CONFIG / "automations.yaml"
    merged_scripts = "\n".join(script_parts)
    merged_autos = "\n".join(auto_parts)

    def _write_merged(dst: Path, content: str, label: str) -> str:
        if not content.strip():
            return f"no {label} content"
        empty = (not dst.is_file()) or (not dst.read_text(encoding="utf-8").strip())
        if force or empty:
            dst.write_text(content, encoding="utf-8")
            return f"wrote {dst} ({label})"
        # Update if destination is still a previous Sunny Island merge (contains our script ids)
        cur = dst.read_text(encoding="utf-8")
        marker = "set_tessie_amps_from_bms" if label == "scripts" else "pack_bms_voltage_stop_tessie"
        if marker in cur and cur != content:
            dst.write_text(content, encoding="utf-8")
            return f"updated app-managed {dst.name}"
        if marker in cur:
            return f"{dst.name} already app-managed"
        return f"skipped {dst.name} (user content present; force_overwrite=false)"

    if script_parts:
        actions.append(_write_merged(scripts_dst, merged_scripts, "scripts"))
    if auto_parts:
        actions.append(_write_merged(autos_dst, merged_autos, "automations"))
    return actions


def main() -> int:
    opts = _load_options()
    auto_sync = bool(opts.get("auto_sync", True))
    install_dashboard = bool(opts.get("install_dashboard", True))
    force = bool(opts.get("force_overwrite", False))
    app_version = _app_version()

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

        # Packages: WebBox Modbus + helpers (always content-sync into /config/packages)
        try:
            for msg in _install_packages():
                actions.append(msg)
                print(f"[sunny_island] {msg}")
        except OSError as exc:
            errors.append(f"packages sync failed: {exc}")
            print(f"[sunny_island] ERROR: {errors[-1]}")

        # Scripts + automations (Tessie amps, pack voltage stop) when empty or app-managed
        try:
            for msg in _install_scripts_automations(force=force):
                actions.append(msg)
                print(f"[sunny_island] {msg}")
        except OSError as exc:
            errors.append(f"scripts/automations sync failed: {exc}")
            print(f"[sunny_island] ERROR: {errors[-1]}")

        if SRC_EXAMPLES.is_dir():
            try:
                # Examples: only install when missing or force (no version gate)
                if force or not DST_EXAMPLES.exists():
                    if DST_EXAMPLES.exists():
                        shutil.rmtree(DST_EXAMPLES)
                    DST_EXAMPLES.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(SRC_EXAMPLES, DST_EXAMPLES)
                    msg = f"installed examples → {DST_EXAMPLES}"
                else:
                    msg = f"skipped (exists, force_overwrite=false): {DST_EXAMPLES}"
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
        "addon_version": app_version,
        "integration_version": _manifest_version(DST_CC) or _manifest_version(SRC_CC),
        "synced_at": now,
        "ha_config": str(HA_CONFIG),
        "installed_path": str(DST_CC) if DST_CC.is_dir() else None,
        "packages": {
            "dir": str(DST_PACKAGES) if DST_PACKAGES.is_dir() else None,
            "files": sorted(p.name for p in DST_PACKAGES.glob("*.yaml"))
            if DST_PACKAGES.is_dir()
            else [],
        },
        "dashboards": {
            "dir": str(DST_DASH_DIR) if DST_DASH_DIR.is_dir() else None,
            "snippet": str(SNIPPET_PATH) if SNIPPET_PATH.is_file() else None,
            "registered": list(LOVELACE_DASHBOARDS.keys()),
            "files": sorted(p.name for p in DST_DASH_DIR.glob("*.yaml"))
            if DST_DASH_DIR.is_dir()
            else [],
            "note": "configuration.yaml is never rewritten; merge lovelace_include.yaml manually",
        },
        "auto_sync": auto_sync,
        "install_dashboard": install_dashboard,
        "force_overwrite": force,
        "actions": actions,
        "errors": errors,
        "ok": not errors and DST_CC.is_dir(),
        "next_steps": [
            "Sidebar Ingress: Sunny Island plant UI",
            "packages: ensure homeassistant.packages: !include_dir_named packages",
            "secrets.yaml: webbox_host (+ optional webbox_password)",
            "Merge dashboards/sunny_island/lovelace_include.yaml under lovelace.dashboards if desired",
            "Settings → Devices & services → Tesla EVTV BMS (WebBox host/password)",
            "Restart HA Core after first integration install/update",
            "Examples: /config/sunny_island_examples/",
        ],
    }

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

    try:
        www_status = BUNDLE / "www" / "status.json"
        www_status.parent.mkdir(parents=True, exist_ok=True)
        www_status.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass

    print(f"[sunny_island] status written → {STATUS_PATH}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
