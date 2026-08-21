import time

import pytest

from engine.download.methods import images


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)


class _Resp:
    def __init__(self, status_code, content_type, chunks):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type is not None else {}
        self._chunks = chunks
        self.closed = False
        self.close_count = 0

    def iter_content(self, n):
        yield from self._chunks

    def close(self):
        self.closed = True
        self.close_count += 1


class _Session:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._resp


def test_response_closed_when_ext_depuis_raises_on_200(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)

    def _boom(*a, **k):
        raise ValueError("ext computation exploded")

    monkeypatch.setattr(images, "_ext_depuis", _boom)

    resp = _Resp(200, "image/png", [b"AB", b"CD"])
    session = _Session(resp)

    with pytest.raises(ValueError):
        images._telecharger_image(session, "https://h/p.png")

    assert resp.closed is True
    assert len(session.calls) == 1


def test_response_closed_when_iter_content_raises_non_request_exc(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)

    class _BoomResp(_Resp):
        def iter_content(self, n):
            raise RuntimeError("stream blew up")

    resp = _BoomResp(200, "image/png", [b"AB"])
    session = _Session(resp)

    with pytest.raises(RuntimeError):
        images._telecharger_image(session, "https://h/p.png")

    assert resp.closed is True
