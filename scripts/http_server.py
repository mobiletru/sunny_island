#!/usr/bin/env python3
"""Tiny Ingress static server — no nginx privilege drop (HAOS AppArmor)."""

from __future__ import annotations

import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WWW = Path(os.environ.get("SI_WWW", "/opt/sunny_island/www"))
CONFIG = Path(os.environ.get("SI_CONFIG_OUT", "/data/config.js"))
ALLOWED = {
    "127.0.0.1",
    "::1",
    "172.30.32.2",  # Supervisor Ingress proxy
}

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
