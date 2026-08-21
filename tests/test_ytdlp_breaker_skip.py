import asyncio
import time

import pytest

from engine.download import _host_breakers as hb
from engine.download import pipeline
from engine.download.queue import CancelToken
from engine.utils.circuit_breaker import CircuitState


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


@pytest.fixture(autouse=True)
def _clear_breakers():
    hb._breakers.clear()
    yield
    hb._breakers.clear()


def _patch_common(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)

    async def no_wait(domain):
        return None

    monkeypatch.setattr(pipeline, "domain_wait", no_wait)
    monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)


def test_ytdlp_skips_host_with_open_breaker(monkeypatch):
    br = hb.get_breaker("blocked.example")
    br._state = CircuitState.OPEN
    br._opened_at = time.monotonic()

    _patch_common(monkeypatch)
    called = []

    async def pool(fn, *a):
        called.append(fn)
        return "out.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    lecteur = {"src": "https://blocked.example/embed", "host": "blocked.example"}
    out = asyncio.run(
        pipeline._ytdlp_sur_lecteurs([lecteur], "/tmp", "ep", "[x]", FakeQueue(), referer="r")
    )

    assert out is None
    assert called == []


def test_ytdlp_runs_when_breaker_closed(monkeypatch):
    _patch_common(monkeypatch)

    async def pool(fn, *a):
        return "out.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    lecteur = {"src": "https://ok.example/embed", "host": "ok.example"}
    out = asyncio.run(
        pipeline._ytdlp_sur_lecteurs([lecteur], "/tmp", "ep", "[x]", FakeQueue(), referer="r")
    )

    assert out == "out.mp4"
