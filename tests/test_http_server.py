"""Ingress Python HTTP server (replaces nginx on HAOS)."""

from __future__ import annotations

import importlib.util
import sys
import threading
from http.client import HTTPConnection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load_http_server():
    path = SCRIPTS / "http_server.py"
    key = "si_http_server"
    if key in sys.modules:
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def test_peer_allowed_supervisor_and_ipv4_mapped():
    http_server = _load_http_server()
    assert http_server.peer_allowed("127.0.0.1") is True
    assert http_server.peer_allowed("::1") is True
    assert http_server.peer_allowed("172.30.32.2") is True
    assert http_server.peer_allowed("172.30.33.1") is True
    assert http_server.peer_allowed("::ffff:172.30.32.2") is True
    assert http_server.peer_allowed("192.168.1.50") is False
    assert http_server.peer_allowed("8.8.8.8") is False


def test_health_and_config_from_localhost(tmp_path, monkeypatch):
    www = tmp_path / "www"
    www.mkdir()
    (www / "index.html").write_text("<html>ok</html>\n", encoding="utf-8")
    config = tmp_path / "config.js"
    config.write_text("const PACK_PREFIX = 'x';\n", encoding="utf-8")
    monkeypatch.setenv("SI_WWW", str(www))
    monkeypatch.setenv("SI_CONFIG_OUT", str(config))

    http_server = _load_http_server()
    httpd = http_server.ThreadingHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type", "").startswith("text/plain")
        assert resp.read() == b"ok\n"

        conn.request("HEAD", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        resp.read()

        conn.request("GET", "/js/config.js")
        resp = conn.getresponse()
        assert resp.status == 200
        assert b"PACK_PREFIX" in resp.read()

        # Core's 401 text/plain is Supervisor, not this app.
        conn.request("GET", "/ingress/validate_session")
        resp = conn.getresponse()
        assert resp.status == 404
        assert resp.getheader("Content-Type") == "application/json"
        body = resp.read()
        assert b"not supervisor" in body
        assert resp.status != 401
    finally:
        httpd.shutdown()
        httpd.server_close()
