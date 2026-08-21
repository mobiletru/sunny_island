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
    spec = importlib.util.spec_from_file_location("si_http_server", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["si_http_server"] = mod
    spec.loader.exec_module(mod)
    return mod


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
        assert resp.read() == b"ok\n"

        conn.request("GET", "/js/config.js")
        resp = conn.getresponse()
        assert resp.status == 200
        assert b"PACK_PREFIX" in resp.read()
    finally:
        httpd.shutdown()
        httpd.server_close()
