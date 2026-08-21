import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from engine.utils import url_pin


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"pong")

    def log_message(self, *a):
        pass


@pytest.fixture
def local_port():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()


def test_pin_routes_unresolvable_host_to_pinned_ip(local_port):
    with url_pin.pin_connection("pin.invalid", "127.0.0.1"):
        r = requests.get(f"http://pin.invalid:{local_port}/", timeout=5)
    assert r.status_code == 200
    assert r.text == "pong"


def test_without_pin_unresolvable_host_fails(local_port):
    with pytest.raises(requests.exceptions.RequestException):
        requests.get(f"http://pin.invalid:{local_port}/", timeout=5)


def test_pin_is_cleared_after_context(local_port):
    with url_pin.pin_connection("pin.invalid", "127.0.0.1"):
        pass
    with pytest.raises(requests.exceptions.RequestException):
        requests.get(f"http://pin.invalid:{local_port}/", timeout=5)


class _PngHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.end_headers()
        self.wfile.write(b"\x89PNG\r\n\x1a\nFAKE")

    def log_message(self, *a):
        pass


@pytest.fixture
def local_png_port():
    srv = HTTPServer(("127.0.0.1", 0), _PngHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()


def test_cover_fetch_uses_pin_to_reach_unresolvable_host(monkeypatch, tmp_path, local_png_port):
    import engine.cache.cover_images as ci

    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "is_safe_url", lambda u: True)
    monkeypatch.setattr(ci, "pin_target", lambda u: ("blocked.invalid", "127.0.0.1"))
    monkeypatch.setattr(ci, "_maybe_resize", lambda d, e: (d, e))

    p = ci.fetch_and_store(f"http://blocked.invalid:{local_png_port}/c")
    assert p is not None and p.exists()
    assert p.read_bytes() == b"\x89PNG\r\n\x1a\nFAKE"


def test_scan_image_fetch_uses_pin(monkeypatch, local_png_port):
    import engine.download.methods.images as im

    monkeypatch.setattr(im, "is_safe_url", lambda u: True)
    monkeypatch.setattr(im, "pin_target", lambda u: ("blocked.invalid", "127.0.0.1"))

    res = im._telecharger_image(requests.Session(), f"http://blocked.invalid:{local_png_port}/p.png")
    assert res is not None
    assert res[0] == b"\x89PNG\r\n\x1a\nFAKE"
