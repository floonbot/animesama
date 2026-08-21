import time

import pytest
import requests

from engine.download.methods import images


@pytest.fixture(autouse=True)
def _reset_is_safe_url():
    original = images.is_safe_url
    yield
    images.is_safe_url = original


@pytest.fixture(autouse=True)
def _sleep_counter(monkeypatch):
    calls = []
    monkeypatch.setattr(time, "sleep", lambda *a, **k: calls.append(a))
    return calls


class _Resp:
    def __init__(self, status_code, content_type=None, chunks=()):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type is not None else {}
        self._chunks = list(chunks)
        self.closed = False

    def iter_content(self, n):
        yield from self._chunks

    def close(self):
        self.closed = True


class _ScriptedSession:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def test_retry_all_429_returns_none_three_calls(monkeypatch, _sleep_counter):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    session = _ScriptedSession([_Resp(429), _Resp(429), _Resp(429)])

    out = images._telecharger_image(session, "https://h/p.jpg")

    assert out is None
    assert len(session.calls) == 3
    assert len(_sleep_counter) == 2


def test_retry_all_503_returns_none_three_calls(monkeypatch, _sleep_counter):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    session = _ScriptedSession([_Resp(503), _Resp(503), _Resp(503)])

    out = images._telecharger_image(session, "https://h/p.jpg")

    assert out is None
    assert len(session.calls) == 3
    assert len(_sleep_counter) == 2


def test_retry_429_then_200_succeeds_two_calls(monkeypatch, _sleep_counter):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    ok = _Resp(200, "image/jpeg", [b"AB", b"CD"])
    session = _ScriptedSession([_Resp(429), ok])

    out = images._telecharger_image(session, "https://h/p.jpg")

    assert out == (b"ABCD", ".jpg")
    assert len(session.calls) == 2
    assert len(_sleep_counter) == 1
    assert ok.closed is True


def test_retry_request_exception_every_attempt(monkeypatch, _sleep_counter):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    session = _ScriptedSession(
        [
            requests.exceptions.RequestException("boom1"),
            requests.exceptions.RequestException("boom2"),
            requests.exceptions.RequestException("boom3"),
        ]
    )

    out = images._telecharger_image(session, "https://h/p.jpg")

    assert out is None
    assert len(session.calls) == 3
    assert len(_sleep_counter) == 2


def test_404_no_retry_single_call(monkeypatch, _sleep_counter):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    resp = _Resp(404)
    session = _ScriptedSession([resp])

    out = images._telecharger_image(session, "https://h/p.jpg")

    assert out is None
    assert len(session.calls) == 1
    assert len(_sleep_counter) == 0
    assert resp.closed is True


def test_host_sur_caches_per_host(monkeypatch):
    calls = []

    def _counting(url):
        calls.append(url)
        return True

    monkeypatch.setattr(images, "is_safe_url", _counting)

    cache: dict[str, bool] = {}
    first = images._host_sur("https://same.example/a.jpg", cache)
    second = images._host_sur("https://same.example/b.jpg", cache)
    third = images._host_sur("https://other.example/c.jpg", cache)

    assert first is True
    assert second is True
    assert third is True
    assert len(calls) == 2
    assert calls[0] == "https://same.example/a.jpg"
    assert calls[1] == "https://other.example/c.jpg"
    assert cache == {"same.example": True, "other.example": True}


def test_host_sur_caches_false_verdict(monkeypatch):
    calls = []

    def _counting(url):
        calls.append(url)
        return False

    monkeypatch.setattr(images, "is_safe_url", _counting)

    cache: dict[str, bool] = {}
    first = images._host_sur("https://blocked.example/x.jpg", cache)
    second = images._host_sur("https://blocked.example/y.jpg", cache)

    assert first is False
    assert second is False
    assert len(calls) == 1
    assert cache == {"blocked.example": False}
