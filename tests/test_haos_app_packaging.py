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
    assert 'version: "2.2.11"' in text
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
    assert "BUILD_VERSION=2.2.11" in text


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
