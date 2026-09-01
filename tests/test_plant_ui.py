"""Plant UI helpers: SI6048 step math, ingress base, unavailable gauges."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_JS = ROOT / "rootfs" / "www" / "js" / "config.js"
APP_JS = ROOT / "rootfs" / "www" / "js" / "app.js"


def _load_http_server():
    key = "si_http_server"
    if key in sys.modules:
        del sys.modules[key]
    path = ROOT / "scripts" / "http_server.py"
    spec = importlib.util.spec_from_file_location(key, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def next_param_step(current, step, direction, min_v=None, max_v=None):
    """Mirror rootfs/www/js/config.js nextParamStep (no browser)."""
    try:
        parsed_step = float(step)
    except (TypeError, ValueError):
        parsed_step = float("nan")
    delta = parsed_step if parsed_step == parsed_step and parsed_step != 0 else 5
    try:
        nxt = float(current)
    except (TypeError, ValueError):
        nxt = 0.0
    if current != current:  # NaN
        nxt = 0.0
    nxt = nxt + delta if direction == "+" else nxt - delta
    if min_v is not None:
        nxt = max(float(min_v), nxt)
    if max_v is not None:
        nxt = min(float(max_v), nxt)
    step_str = str(delta)
    decimals = len(step_str.split(".")[1]) if "." in step_str else 0
    return float(f"{nxt:.{decimals}f}")


def test_next_param_step_keeps_cell_voltage_hundredths():
    """Regression: Math.round(2.27 + 0.01) was 2 — SI would write 2.00 V/cell."""
    assert next_param_step(2.27, 0.01, "+", 1.5, 2.7) == 2.28
    assert next_param_step(2.27, 0.01, "-", 1.5, 2.7) == 2.26
    assert next_param_step(2.01, 0.01, "+", 1.5, 2.7) == 2.02
    assert next_param_step(1.5, 0.01, "-", 1.5, 2.7) == 1.5
    assert next_param_step(2.7, 0.01, "+", 1.5, 2.7) == 2.7


def test_next_param_step_keeps_hz_tenths():
    assert next_param_step(59.3, 0.1, "+", 50, 62) == 59.4
    assert next_param_step(60.0, 0.1, "-", 50, 70) == 59.9
    assert next_param_step(57.3, 0.1, "-", 50, 62) == 57.2


def test_next_param_step_ints_stay_ints():
    assert next_param_step(48, 1, "+", 41, 63) == 49
    assert next_param_step(100, 10, "-", 10, 1200) == 90


def test_config_js_defines_next_param_step():
    text = CONFIG_JS.read_text(encoding="utf-8")
    assert "function nextParamStep(" in text
    app = APP_JS.read_text(encoding="utf-8")
    assert "Math.round(next)" not in app
    assert "nextParamStep(" in app


def test_gauges_reset_when_unavailable():
    app = APP_JS.read_text(encoding="utf-8")
    assert "$('#g-soc-val').textContent = '—'" in app
    assert "$('#g-volts-val').textContent = '—'" in app
    assert "$('#g-amps-val').textContent = '—'" in app


def test_ingress_base_href_from_supervisor_header():
    http = _load_http_server()
    assert http.ingress_base_href("/4afc027a_sunny_island") == "/4afc027a_sunny_island/"
    assert http.ingress_base_href("/4afc027a_sunny_island/") == "/4afc027a_sunny_island/"
    assert (
        http.ingress_base_href("/api/hassio_ingress/abcToken")
        == "/api/hassio_ingress/abcToken/"
    )
    assert http.ingress_base_href("") == ""
    assert http.ingress_base_href("/") == ""
    assert http.ingress_base_href("https://evil.example/") == ""
    assert http.ingress_base_href("<script>") == ""


def test_inject_ingress_base_once():
    http = _load_http_server()
    html = "<html><head>\n<title>SI</title></head><body></body></html>"
    out = http.inject_ingress_base(html, "/4afc027a_sunny_island")
    assert '<base href="/4afc027a_sunny_island/">' in out
    again = http.inject_ingress_base(out, "/4afc027a_sunny_island")
    assert again.count("<base ") == 1
    shipped = (ROOT / "rootfs" / "www" / "index.html").read_text(encoding="utf-8")
    injected = http.inject_ingress_base(shipped, "/4afc027a_sunny_island")
    assert '<base href="/4afc027a_sunny_island/">' in injected


def test_http_health_and_ingress_index(tmp_path, monkeypatch):
    """Watchdog /health and X-Ingress-Path <base> against the real handler."""
    import threading
    from http.client import HTTPConnection

    http = _load_http_server()
    www = tmp_path / "www"
    www.mkdir()
    (www / "index.html").write_text(
        "<html><head><title>SI</title></head><body>ok</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(http, "WWW", www)
    httpd = http.ThreadingHTTPServer(("127.0.0.1", 0), http.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        assert body == b"ok\n"
        conn.close()

        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/", headers={"X-Ingress-Path": "/4afc027a_sunny_island"})
        resp = conn.getresponse()
        page = resp.read().decode()
        assert resp.status == 200
        assert '<base href="/4afc027a_sunny_island/">' in page
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
