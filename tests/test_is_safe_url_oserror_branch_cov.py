"""Regression: is_safe_url must stay total (return False, never raise). A
getaddrinfo failure that is an OSError but not a socket.gaierror (e.g. a resolver
timeout) previously propagated through validate_external_url and out of
is_safe_url (which only catches UnsafeUrlError), reaching callers such as
cover_images.fetch_and_store unguarded. Widening the caught set to OSError makes
resolution failure fail-closed.
"""

import engine.utils.security as security


def test_is_safe_url_false_on_plain_oserror(monkeypatch):
    def _boom(*a, **k):
        raise OSError("resolver exploded")

    monkeypatch.setattr(security.socket, "getaddrinfo", _boom)
    assert security.is_safe_url("https://example.com/video.m3u8") is False


def test_is_safe_url_false_on_timeout(monkeypatch):
    def _boom(*a, **k):
        raise TimeoutError("slow dns")

    monkeypatch.setattr(security.socket, "getaddrinfo", _boom)
    assert security.is_safe_url("https://example.com/video.m3u8") is False
