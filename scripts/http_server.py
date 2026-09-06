#!/usr/bin/env python3
"""Tiny Ingress static server — no nginx privilege drop (HAOS AppArmor).

Also proxies Home Assistant WebSocket at /ha-ws using SUPERVISOR_TOKEN so the
plant UI does not need a pasted long-lived token (Ingress is already authed).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import select
import socket
import struct
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

WWW = Path(os.environ.get("SI_WWW", "/opt/sunny_island/www"))
CONFIG = Path(os.environ.get("SI_CONFIG_OUT", "/data/config.js"))
ALLOWED = {
    "127.0.0.1",
    "::1",
    "172.30.32.2",  # Supervisor Ingress proxy
}
HA_WS_PATHS = {"/ha-ws", "/ha-ws/"}
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
HA_WS_DEFAULT = "ws://supervisor/core/websocket"

# Supervisor sets X-Ingress-Path (e.g. /4afc027a_sunny_island or
# /api/hassio_ingress/<token>). Relative css/js break without a <base>
# when the browser URL has no trailing slash.
_INGRESS_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]*$")


def ingress_base_href(header: str | None) -> str:
    """Safe <base href> from X-Ingress-Path, or '' if missing/invalid."""
    raw = (header or "").strip()
    if not raw or raw == "/":
        return ""
    if not _INGRESS_PATH_RE.match(raw):
        return ""
    return raw.rstrip("/") + "/"


def inject_ingress_base(html: str, header: str | None) -> str:
    base = ingress_base_href(header)
    if not base or "<base " in html.lower():
        return html
    return html.replace("<head>", f'<head>\n  <base href="{base}">', 1)


def supervisor_token() -> str:
    return (os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HASSIO_TOKEN") or "").strip()


def ha_websocket_url() -> str:
    return (os.environ.get("SI_HA_WS") or HA_WS_DEFAULT).strip() or HA_WS_DEFAULT


def ws_accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_ws_frame(payload: bytes, opcode: int = 1, mask: bool = False) -> bytes:
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))
    n = len(payload)
    mask_bit = 0x80 if mask else 0
    if n < 126:
        header.append(mask_bit | n)
    elif n < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", n))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", n))
    data = payload
    if mask:
        key = os.urandom(4)
        header.extend(key)
        data = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return bytes(header) + data


def decode_ws_frame(buf: bytes) -> Optional[tuple[int, bytes, bytes]]:
    """Return (opcode, payload, remainder) or None if buf is incomplete."""
    if len(buf) < 2:
        return None
    b0, b1 = buf[0], buf[1]
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    n = b1 & 0x7F
    idx = 2
    if n == 126:
        if len(buf) < 4:
            return None
        n = struct.unpack("!H", buf[2:4])[0]
        idx = 4
    elif n == 127:
        if len(buf) < 10:
            return None
        n = struct.unpack("!Q", buf[2:10])[0]
        idx = 10
    mask_key = b""
    if masked:
        if len(buf) < idx + 4:
            return None
        mask_key = buf[idx : idx + 4]
        idx += 4
    if len(buf) < idx + n:
        return None
    payload = buf[idx : idx + n]
    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return opcode, payload, buf[idx + n :]


def _read_http_headers(sock: socket.socket, leftover: bytes = b"") -> tuple[bytes, bytes]:
    data = leftover
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("eof during websocket handshake")
        data += chunk
        if len(data) > 65536:
            raise OSError("handshake too large")
    head, rest = data.split(b"\r\n\r\n", 1)
    return head, rest


def connect_ha_websocket(token: str) -> tuple[socket.socket, bytes]:
    url = urlsplit(ha_websocket_url())
    host = url.hostname or "supervisor"
    port = url.port or (443 if url.scheme == "wss" else 80)
    path = url.path or "/core/websocket"
    sock = socket.create_connection((host, port), timeout=10)
    sock.settimeout(20)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Authorization: Bearer {token}\r\n"
        "\r\n"
    )
    sock.sendall(req.encode("ascii"))
    head, rest = _read_http_headers(sock)
    status = head.split(b"\r\n", 1)[0]
    if b"101" not in status:
        sock.close()
        raise OSError("HA websocket upgrade failed: " + status.decode("ascii", "replace"))
    return sock, rest


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW), **kwargs)

    def handle(self):
        peer = self.client_address[0]
        if peer not in ALLOWED and not peer.startswith("172.30.32."):
            try:
                self.send_error(403, "Forbidden")
            except OSError:
                pass
            return
        return super().handle()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in HA_WS_PATHS:
            self._proxy_ha_websocket()
            return
        if path in ("/health", "/health/"):
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/js/config.js", "/js/config.js/"):
            data = CONFIG.read_bytes() if CONFIG.is_file() else b""
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        translated = self.translate_path(path)
        if translated.endswith("index.html") and os.path.isfile(translated):
            try:
                html = Path(translated).read_text(encoding="utf-8")
            except OSError:
                return super().do_GET()
            html = inject_ingress_base(html, self.headers.get("X-Ingress-Path"))
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def _proxy_ha_websocket(self) -> None:
        token = supervisor_token()
        key = (self.headers.get("Sec-WebSocket-Key") or "").strip()
        if not token:
            self.send_error(503, "Supervisor token missing")
            return
        if not key:
            self.send_error(400, "Expected WebSocket upgrade")
            return
        try:
            ha_sock, ha_buf = connect_ha_websocket(token)
        except OSError:
            self.send_error(502, "Home Assistant websocket unavailable")
            return
        accept = ws_accept_key(key)
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True
        browser = self.connection
        browser_buf = b""
        ha_authed = False

        def pump_browser() -> bool:
            nonlocal browser_buf
            while True:
                decoded = decode_ws_frame(browser_buf)
                if not decoded:
                    return False
                opcode, payload, browser_buf = decoded
                if opcode == 8:
                    ha_sock.sendall(encode_ws_frame(payload, 8, mask=True))
                    return True
                if opcode == 9:
                    browser.sendall(encode_ws_frame(payload, 10, mask=False))
                    continue
                if opcode == 10:
                    continue
                if opcode == 1:
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        msg = None
                    if isinstance(msg, dict) and msg.get("type") == "auth":
                        continue
                ha_sock.sendall(encode_ws_frame(payload, opcode, mask=True))

        def pump_ha() -> bool:
            nonlocal ha_buf, ha_authed
            while True:
                decoded = decode_ws_frame(ha_buf)
                if not decoded:
                    return False
                opcode, payload, ha_buf = decoded
                if opcode == 8:
                    browser.sendall(encode_ws_frame(payload, 8, mask=False))
                    return True
                if opcode == 9:
                    ha_sock.sendall(encode_ws_frame(payload, 10, mask=True))
                    continue
                if opcode == 1 and not ha_authed:
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        msg = {}
                    if msg.get("type") == "auth_required":
                        auth = json.dumps(
                            {"type": "auth", "access_token": token}
                        ).encode("utf-8")
                        ha_sock.sendall(encode_ws_frame(auth, 1, mask=True))
                        continue
                    if msg.get("type") == "auth_ok":
                        ha_authed = True
                    if msg.get("type") == "auth_invalid":
                        browser.sendall(encode_ws_frame(payload, 1, mask=False))
                        return True
                browser.sendall(encode_ws_frame(payload, opcode, mask=False))

        try:
            # auth_required often arrives in the upgrade leftover — drain it
            # before select(), or the proxy waits forever for more HA bytes.
            if pump_ha():
                return
            while True:
                ready, _, _ = select.select([browser, ha_sock], [], [], 60)
                if not ready:
                    continue
                if browser in ready:
                    chunk = browser.recv(65536)
                    if not chunk:
                        break
                    browser_buf += chunk
                    if pump_browser():
                        return
                if ha_sock in ready:
                    chunk = ha_sock.recv(65536)
                    if not chunk:
                        break
                    ha_buf += chunk
                    if pump_ha():
                        return
        except OSError:
            pass
        finally:
            try:
                ha_sock.close()
            except OSError:
                pass

    def translate_path(self, path: str) -> str:
        translated = super().translate_path(path)
        if os.path.isdir(translated):
            index = os.path.join(translated, "index.html")
            if os.path.isfile(index):
                return index
        if not os.path.isfile(translated):
            fallback = WWW / "index.html"
            if fallback.is_file():
                return str(fallback)
        return translated

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> int:
    WWW.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("0.0.0.0", 8098), Handler)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
