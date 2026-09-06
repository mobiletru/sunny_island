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


def test_ws_frame_roundtrip_masked_and_plain():
    http = _load_http_server()
    payload = b'{"type":"auth_ok"}'
    framed = http.encode_ws_frame(payload, opcode=1, mask=True)
    decoded = http.decode_ws_frame(framed)
    assert decoded is not None
    opcode, body, rest = decoded
    assert opcode == 1
    assert body == payload
    assert rest == b""
    plain = http.encode_ws_frame(payload, opcode=1, mask=False)
    opcode, body, rest = http.decode_ws_frame(plain)
    assert body == payload
    assert rest == b""


def test_ingress_uses_supervisor_websocket_not_user_token():
    http = _load_http_server()
    assert "/ha-ws" in http.HA_WS_PATHS
    client = (ROOT / "rootfs" / "www" / "js" / "ha-client.js").read_text(encoding="utf-8")
    assert "ha-ws" in client
    assert "/api/websocket" not in client
    app = APP_JS.read_text(encoding="utf-8")
    assert "function tryConnect()" in app
    assert "if (!token)" not in app
    assert "connectHA()" in app
    html = (ROOT / "rootfs" / "www" / "index.html").read_text(encoding="utf-8")
    assert "token-input" not in html
    assert "no token needed" in html.lower()
    render = (ROOT / "scripts" / "render_config.py").read_text(encoding="utf-8")
    assert "localStorage.setItem" not in render
    html = (ROOT / "rootfs" / "www" / "index.html").read_text(encoding="utf-8")
    assert "js/app.js?v=" in html
    assert "js/ha-client.js?v=" in html


def test_ha_ws_http_errors_without_token_or_upgrade(tmp_path, monkeypatch):
    import threading
    from http.client import HTTPConnection

    http = _load_http_server()
    www = tmp_path / "www"
    www.mkdir()
    monkeypatch.setattr(http, "WWW", www)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("HASSIO_TOKEN", raising=False)
    httpd = http.ThreadingHTTPServer(("127.0.0.1", 0), http.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/ha-ws")
        resp = conn.getresponse()
        assert resp.status == 503
        resp.read()
        conn.close()

        monkeypatch.setenv("SUPERVISOR_TOKEN", "supertok")
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/ha-ws")
        resp = conn.getresponse()
        assert resp.status == 400
        resp.read()
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_ws_proxy_auths_from_handshake_leftover_and_swallows_browser_auth(
    tmp_path, monkeypatch
):
    """HA often sends auth_required in the 101 leftover; proxy must drain it."""
    import base64
    import json
    import os
    import socket
    import threading
    import time

    http = _load_http_server()
    www = tmp_path / "www"
    www.mkdir()
    monkeypatch.setattr(http, "WWW", www)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supertok")
    monkeypatch.delenv("HASSIO_TOKEN", raising=False)

    ha_msgs = []
    ha_ready = threading.Event()
    ha_port = {}
    stop = threading.Event()

    def ha_server():
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        ha_port["n"] = srv.getsockname()[1]
        ha_ready.set()
        srv.settimeout(5)
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        try:
            head, rest = http._read_http_headers(conn)
            assert b"Authorization: Bearer supertok" in head
            key = ""
            for line in head.decode("ascii", "replace").split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            accept = http.ws_accept_key(key)
            auth_req = http.encode_ws_frame(
                b'{"type":"auth_required","ha_version":"2024.1.0"}',
                opcode=1,
                mask=False,
            )
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n"
                    "\r\n"
                ).encode("ascii")
                + auth_req
            )
            buf = rest
            deadline = time.time() + 5
            conn.settimeout(0.2)
            while time.time() < deadline and not stop.is_set():
                decoded = http.decode_ws_frame(buf)
                if decoded:
                    opcode, payload, buf = decoded
                    if opcode == 1:
                        ha_msgs.append(json.loads(payload.decode("utf-8")))
                        if ha_msgs[-1].get("type") == "auth":
                            conn.sendall(
                                http.encode_ws_frame(
                                    b'{"type":"auth_ok","ha_version":"2024.1.0"}',
                                    opcode=1,
                                    mask=False,
                                )
                            )
                    continue
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
        finally:
            try:
                conn.close()
            except OSError:
                pass
            srv.close()

    ha_thread = threading.Thread(target=ha_server, daemon=True)
    ha_thread.start()
    assert ha_ready.wait(2)
    monkeypatch.setenv("SI_HA_WS", f"ws://127.0.0.1:{ha_port['n']}/core/websocket")

    httpd = http.ThreadingHTTPServer(("127.0.0.1", 0), http.Handler)
    ui_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    ui_thread.start()
    try:
        host, port = httpd.server_address
        sock = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        sock.sendall(
            (
                f"GET /ha-ws HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            ).encode("ascii")
        )
        head, rest = http._read_http_headers(sock)
        assert b"101" in head.split(b"\r\n", 1)[0]
        buf = rest
        sock.settimeout(5)
        deadline = time.time() + 5
        got_ok = None
        while time.time() < deadline and got_ok is None:
            decoded = http.decode_ws_frame(buf)
            if decoded:
                opcode, payload, buf = decoded
                if opcode == 1:
                    got_ok = json.loads(payload.decode("utf-8"))
                continue
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        assert got_ok == {"type": "auth_ok", "ha_version": "2024.1.0"}
        sock.sendall(
            http.encode_ws_frame(
                b'{"type":"auth","access_token":"userjwt"}', opcode=1, mask=True
            )
        )
        sock.sendall(
            http.encode_ws_frame(
                b'{"id":1,"type":"subscribe_entities","entity_ids":["sensor.x"]}',
                opcode=1,
                mask=True,
            )
        )
        deadline = time.time() + 5
        while time.time() < deadline:
            if any(m.get("type") == "subscribe_entities" for m in ha_msgs):
                break
            time.sleep(0.05)
        assert ha_msgs[0] == {"type": "auth", "access_token": "supertok"}
        assert not any(m.get("access_token") == "userjwt" for m in ha_msgs)
        assert any(m.get("type") == "subscribe_entities" for m in ha_msgs)
        sock.close()
    finally:
        stop.set()
        httpd.shutdown()
        httpd.server_close()
