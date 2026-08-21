"""Tests for entry-data normalize and version-gated install decisions."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "tesla_evtv_bms"
SCRIPTS = ROOT / "scripts"


def _load_pkg_mod(mod_name: str, file_name: str):
    pkg = "tesla_evtv_bms"
    if pkg not in sys.modules:
        m = types.ModuleType(pkg)
        m.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        sys.modules[pkg] = m
    full = f"{pkg}.{mod_name}"
    if full in sys.modules:
        return sys.modules[full]
    path = COMPONENT / file_name
    spec = importlib.util.spec_from_file_location(full, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    setattr(sys.modules[pkg], mod_name, mod)
    return mod


const = _load_pkg_mod("const", "const.py")
_load_pkg_mod("runtime", "runtime.py")


def _load_script(name: str):
    path = SCRIPTS / name
    # Fresh load each time so tests don't share mutated module globals
    key = f"si_script_{name.replace('.', '_')}"
    if key in sys.modules:
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def test_default_cells_is_12s():
    assert const.DEFAULT_CELLS_IN_SERIES == 12
    assert const.DEFAULT_PORT == 6550


def test_normalize_strips_webbox_url_and_prefix():
    data = const.normalize_entry_data(
        {
            "name": "Pack",
            "port": "6550",
            "entity_prefix": "Battery Storage Tesla Pack",
            "pack_size": 75,
            "cells_in_series": 12,
            "min_cell_volts": 3.2,
            "max_cell_volts": 4.1,
            "webbox_host": "https://192.168.1.50/home.ajax",
            "webbox_password": " secret ",
            "webbox_scan_interval": 20,
        }
    )
    assert data["webbox_host"] == "192.168.1.50"
    assert data["webbox_password"] == "secret"
    assert data["entity_prefix"] == "battery_storage_tesla_pack"
    assert data["port"] == 6550
    assert data["webbox_scan_interval"] == 20


def test_normalize_preserve_port():
    existing = {
        "port": 6550,
        "name": "Old",
        "entity_prefix": "battery_storage_tesla_pack",
    }
    data = const.normalize_entry_data(
        {"name": "New", "webbox_host": ""},
        existing=existing,
        preserve_port=True,
    )
    assert data["port"] == 6550
    assert data["name"] == "New"


def test_should_sync_on_version_mismatch():
    install = _load_script("install_integration.py")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        src, dst = base / "src", base / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "manifest.json").write_text('{"version": "1.8.2"}\n')
        (dst / "manifest.json").write_text('{"version": "1.8.0"}\n')
        ok, reason = install._should_sync_tree(src, dst, force=False)
        assert ok is True
        assert "1.8.0" in reason and "1.8.2" in reason


def test_should_skip_same_version():
    install = _load_script("install_integration.py")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        src, dst = base / "src", base / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "manifest.json").write_text('{"version": "1.8.2"}\n')
        (dst / "manifest.json").write_text('{"version": "1.8.2"}\n')
        ok, reason = install._should_sync_tree(src, dst, force=False)
        assert ok is False
        assert "skipped" in reason


def test_force_overwrite_always_syncs():
    install = _load_script("install_integration.py")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        src, dst = base / "src", base / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "manifest.json").write_text('{"version": "1.8.2"}\n')
        (dst / "manifest.json").write_text('{"version": "1.8.2"}\n')
        ok, reason = install._should_sync_tree(src, dst, force=True)
        assert ok is True
        assert reason == "force_overwrite"


def test_render_config_requires_template():
    render = _load_script("render_config.py")
    try:
        render._build_config_js("p", "e", "", "const OTHER = 1;\n")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "PACK_PREFIX" in str(exc)


def test_render_config_rewrites_prefixes():
    render = _load_script("render_config.py")
    template = (
        "const PACK_PREFIX = 'old';\n"
        "const ENVOY_PREFIX = 'sensor.old';\n"
        "const DISCHARGE_IS_NEGATIVE = true;\n"
    )
    out = render._build_config_js("new_pack", "sensor.envoy_x", "", template)
    assert 'const PACK_PREFIX = "new_pack";' in out
    assert 'const ENVOY_PREFIX = "sensor.envoy_x";' in out
    assert "DISCHARGE_IS_NEGATIVE" in out


def test_bms_flow_payload_defaults():
    setup = _load_script("bms_setup.py")
    payload = setup._bms_flow_payload({})
    assert payload["port"] == 6550
    assert payload["entity_prefix"] == "battery_storage_tesla_pack"
    assert payload["name"] == "Tesla Pack"
    assert payload["cells_in_series"] == 12
    assert payload["webbox_modbus"] is True
    assert payload["webbox_host"] == ""


def test_bms_flow_payload_from_options():
    setup = _load_script("bms_setup.py")
    payload = setup._bms_flow_payload(
        {
            "pack_prefix": "battery_storage_tesla_pack",
            "bms_udp_port": "6551",
            "webbox_host": " 192.168.100.180 ",
        }
    )
    assert payload["port"] == 6551
    assert payload["webbox_host"] == "192.168.100.180"


def test_ensure_packages_include_appends_when_missing():
    setup = _load_script("bms_setup.py")
    with tempfile.TemporaryDirectory() as td:
        ha = Path(td)
        setup.HA_CONFIG = ha
        cfg = ha / "configuration.yaml"
        cfg.write_text("default_config:\n", encoding="utf-8")
        msg = setup._ensure_packages_include()
        text = cfg.read_text(encoding="utf-8")
        assert "include_dir_named packages" in text
        assert "added" in msg
        again = setup._ensure_packages_include()
        assert again == "packages include already present"


def test_ha_token_falls_back_to_options():
    setup = _load_script("bms_setup.py")
    saved = {
        k: os.environ.pop(k)
        for k in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN")
        if k in os.environ
    }
    try:
        assert setup._ha_token() == ""
        assert setup._ha_token({"ha_token": "abc"}) == "abc"
    finally:
        os.environ.update(saved)


def test_retired_app_slugs_and_not_self():
    install = _load_script("install_integration.py")
    assert install.addon_bare_slug("local_sunny_island_detail") == "sunny_island_detail"
    assert install.addon_bare_slug("abcd1234_tesla_evtv_bms") == "tesla_evtv_bms"
    assert install.addon_bare_slug("local_sunny_island") == "sunny_island"
    assert install.is_self_app("local_sunny_island") is True
    assert install.is_retired_app(slug="local_tesla_evtv_bms") is True
    assert install.is_retired_app(slug="local_tesla_evtv_bms_monitor") is True
    assert install.is_retired_app(slug="local_tesla_evtv_sunny_island") is True
    assert install.is_retired_app(slug="ffffeeee_sunny_island_detail") is True
    assert install.is_retired_app(slug="local_sunny_island") is False
    assert install.is_retired_app(slug="local_webbox", name="Sunny Island WebBox") is True
    assert install.is_retired_app(slug="local_webbox", name="Some other WebBox") is False
    assert install.is_retired_panel("sunny-island") is True
    assert install.is_retired_panel("local_sunny_island") is False


def test_unify_hides_retired_ingress_panels():
    install = _load_script("install_integration.py")
    with tempfile.TemporaryDirectory() as td:
        storage = Path(td) / ".storage"
        storage.mkdir()
        user = storage / "frontend.user_data_abc"
        user.write_text(
            json.dumps(
                {
                    "data": {
                        "sidebar": {
                            "hiddenPanels": [],
                            "panelOrder": [
                                "local_sunny_island",
                                "local_sunny_island_detail",
                                "sunny-island",
                                "abcd1234_tesla_evtv_bms",
                            ],
                        }
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )
        install.HA_CONFIG = Path(td)
        msgs = install._unify_ha_sidebar_entry(extra_panels={"local_webbox"})
        data = json.loads(user.read_text(encoding="utf-8"))
        sidebar = data["data"]["sidebar"]
        assert "local_sunny_island" in sidebar["panelOrder"]
        assert "local_sunny_island_detail" not in sidebar["panelOrder"]
        assert "abcd1234_tesla_evtv_bms" not in sidebar["panelOrder"]
        assert "sunny-island" not in sidebar["panelOrder"]
        assert "local_sunny_island_detail" in sidebar["hiddenPanels"]
        assert "local_webbox" in sidebar["hiddenPanels"]
        assert any("hid" in m or "sidebar" in m for m in msgs)


def test_retire_legacy_apps_stops_and_hides_leftovers():
    install = _load_script("install_integration.py")
    calls: list[tuple[str, str, dict | None]] = []

    def fake_supervisor(method: str, path: str, body: dict | None = None):
        calls.append((method, path, body))
        if method == "GET" and path == "/addons":
            return {
                "addons": [
                    {
                        "slug": "local_sunny_island",
                        "name": "Sunny Island",
                        "installed": True,
                        "state": "started",
                        "ingress_panel": True,
                    },
                    {
                        "slug": "local_sunny_island_detail",
                        "name": "Sunny Island Detail",
                        "installed": True,
                        "state": "started",
                        "ingress_panel": True,
                    },
                    {
                        "slug": "abcd1234_tesla_evtv_bms",
                        "name": "Tesla EVTV BMS",
                        "installed": True,
                        "state": "stopped",
                        "ingress_panel": False,
                    },
                ]
            }
        return {}

    install._supervisor_request = fake_supervisor
    extra, msgs = install._retire_legacy_apps()
    assert "local_sunny_island_detail" in extra
    assert "abcd1234_tesla_evtv_bms" in extra
    assert "local_sunny_island" not in extra
    assert any("stopped retired app Sunny Island Detail" in m for m in msgs)
    assert any("retired app present (already stopped): Tesla EVTV BMS" in m for m in msgs)
    assert ("POST", "/addons/local_sunny_island_detail/stop", None) in calls
    assert (
        "POST",
        "/addons/local_sunny_island_detail/options",
        {"ingress_panel": False},
    ) in calls
    assert not any(path.endswith("/local_sunny_island/stop") for _, path, _ in calls)
