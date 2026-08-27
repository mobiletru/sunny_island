#!/usr/bin/env python3
"""Tiny Ingress static server — no nginx privilege drop (HAOS AppArmor).

This process is the add-on web UI on :8098. It does **not** implement
Supervisor ``/ingress/validate_session``. That call is Core → Supervisor
(172.30.32.2). A 401 with ``text/plain; charset=utf-8`` there is Supervisor
``HTTPUnauthorized`` (stale leftover Ingress panel / cookie), not this server.
"""

from __future__ import annotations

import ipaddress
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WWW = Path(os.environ.get("SI_WWW", "/opt/sunny_island/www"))
CONFIG = Path(os.environ.get("SI_CONFIG_OUT", "/data/config.js"))

# Supervisor + add-on Docker networks (HAOS). Ingress proxy is 172.30.32.2.
ALLOWED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("172.30.32.0/23"),
    ipaddress.ip_network("172.30.33.0/24"),
)


def _unwrap_peer(peer: str) -> str:
    """Turn IPv4-mapped IPv6 (::ffff:172.30.32.2) into IPv4."""
    text = (peer or "").strip()
    if text.startswith("::ffff:"):
        return text[7:]
    return text


def peer_allowed(peer: str) -> bool:
    """True for loopback and the HAOS Supervisor/add-on networks."""
    text = _unwrap_peer(peer)
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    return any(addr in net for net in ALLOWED_NETWORKS)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW), **kwargs)

    def handle(self):
        peer = self.client_address[0]
        if not peer_allowed(peer):
            try:
                # 403, never 401 — 401 is Supervisor's ingress-session response.
                self.send_error(403, "Forbidden")
            except OSError:
                pass
            return
        return super().handle()

    def _serve_health(self, *, include_body: bool) -> None:
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def do_HEAD(self):
        path = self.path.split("?", 1)[0]
        if path in ("/health", "/health/"):
            self._serve_health(include_body=False)
            return
        return super().do_HEAD()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/health", "/health/"):
            self._serve_health(include_body=True)
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
        # Supervisor owns /ingress/* ; never mimic a session 401 here.
        if path.startswith("/ingress/"):
            body = b'{"result":"error","message":"not supervisor"}\n'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

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
