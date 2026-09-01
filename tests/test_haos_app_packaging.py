"""HAOS App / Supervisor store packaging checks (no Supervisor required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_repository_yaml_identifies_app_store_repo():
    text = _read("repository.yaml")
    assert "name: Sunny Island" in text
    assert "https://github.com/mobiletru/sunny_island" in text
    assert "maintainer:" in text


def test_config_yaml_required_app_keys():
    text = _read("config.yaml")
    assert 'name: Sunny Island' in text
    assert 'version: "2.2.17"' in text
    assert "auto_setup_bms: true" in text
    assert "bms_udp_port: 6550" in text
    assert "slug: sunny_island" in text
    assert "aarch64" in text and "amd64" in text
    assert "ingress: true" in text
    assert "ingress_port: 8098" in text
    assert "panel_title: Sunny Island" in text
    assert "homeassistant_api: true" in text
    assert "hassio_api: true" in text
    assert "init: false" in text


def test_config_map_uses_homeassistant_config_at_slash_config():
    text = _read("config.yaml")
    assert "homeassistant_config" in text
    assert "path: /config" in text
    assert "read_only: false" in text
    # Legacy shorthand is deprecated and ignored when mixed with new types.
    assert "config:rw" not in text
    assert "addon_config" not in text


def test_dockerfile_uses_official_multiarch_base_and_app_label():
    text = _read("Dockerfile")
    assert "ghcr.io/home-assistant/base:3.21" in text
    assert 'io.hass.type="app"' in text
    assert "BUILD_VERSION=2.2.17" in text
    assert "COPY scripts/bms_setup.py" in text


def test_presentation_and_security_files_exist():
    icon = ROOT / "icon.png"
    logo = ROOT / "logo.png"
    assert icon.is_file() and icon.stat().st_size > 100
    assert logo.is_file() and logo.stat().st_size > 100
    assert icon.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert logo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert (ROOT / "apparmor.txt").is_file()
    assert "profile sunny_island" in _read("apparmor.txt")
    assert (ROOT / "DOCS.md").is_file()
    assert (ROOT / "CHANGELOG.md").is_file()


def test_translations_cover_schema_keys():
    schema_keys = (
        "auto_sync",
        "install_dashboard",
        "force_overwrite",
        "pack_prefix",
        "envoy_prefix",
        "ha_token",
        "log_level",
    )
    text = _read("translations/en.yaml")
    for key in schema_keys:
        assert f"{key}:" in text
    assert "8098/tcp:" in text


def test_ingress_nginx_allows_supervisor_only():
    text = _read("rootfs/etc/nginx/nginx.conf")
    assert "allow 172.30.32.2" in text
    assert "allow 127.0.0.1" in text
    assert "deny all" in text
    assert "listen 8098" in text
    assert "error_log /dev/stderr" in text
    assert "pid /tmp/nginx/nginx.pid" in text
    assert "user root;" in text
    assert "/var/log/nginx" not in text
    assert "/var/lib/nginx" not in text


def test_run_sh_avoids_readonly_nginx_dirs():
    text = _read("run.sh")
    assert "/var/lib/nginx" not in "\n".join(
        line for line in text.splitlines() if line.strip().startswith("mkdir")
    )
    assert "nginx" not in [
        tok for line in text.splitlines() if line.strip().startswith("exec") for tok in line.split()
    ]
    assert "with-contenv" in text
    assert "--ensure-bms" in text
    assert "bms_setup.py" in text
    assert "http_server.py" in text


def test_translations_cover_bms_schema_keys():
    text = _read("translations/en.yaml")
    for key in ("auto_setup_bms", "bms_udp_port", "webbox_host", "webbox_password"):
        assert f"{key}:" in text


def test_app_version_file_matches_config_and_dockerfile():
    """APP_VERSION is the app version (not tesla_evtv_bms manifest)."""
    app_ver = (ROOT / "APP_VERSION").read_text(encoding="utf-8").strip()
    assert app_ver == "2.2.17"
    assert f'version: "{app_ver}"' in _read("config.yaml")
    assert f"BUILD_VERSION={app_ver}" in _read("Dockerfile")
    manifest = (ROOT / "custom_components" / "tesla_evtv_bms" / "manifest.json").read_text(
        encoding="utf-8"
    )
    assert '"version": "1.9.16"' in manifest
    assert app_ver not in ("1.9.14", "1.9.15", "1.9.16")


def test_host_network_false_udp_is_core_side():
    """LiteCAN UDP 6550 is bound in HA Core; the app must not steal host net."""
    text = _read("config.yaml")
    assert "host_network: false" in text
    assert "6550/udp" not in text
    assert "bms_udp_port: 6550" in text
    init = _read("custom_components/tesla_evtv_bms/__init__.py")
    assert 'sock.bind(("", port))' in init


def test_set_webbox_service_is_registered():
    init = _read("custom_components/tesla_evtv_bms/__init__.py")
    assert "apply_si_modbus_derived" in init
    assert "SERVICE_SET_WEBBOX" in init
    assert "_handle_set_webbox" in init
    assert "webbox_data_updates" in init
    services = _read("custom_components/tesla_evtv_bms/services.yaml")
    assert services.startswith("set_webbox:")
