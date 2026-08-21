import asyncio

import pytest

from engine.download import _host_breakers as hb
from engine.download import pipeline
from engine.download.methods.ytdlp_engine import RateLimitError
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
    monkeypatch.setattr(pipeline, "domain_apply_penalty", lambda d: None)


def _run_once(host):
    lecteur = {"src": f"https://{host}/embed", "host": host}
    return asyncio.run(
        pipeline._ytdlp_sur_lecteurs([lecteur], "/tmp", "ep", "[x]", FakeQueue(), referer="r")
    )


def test_ytdlp_runtime_failures_eventually_open_breaker(monkeypatch):
    _patch_common(monkeypatch)

    async def pool(fn, *a):
        raise RuntimeError("dead host")

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    for _ in range(hb._FAILURE_THRESHOLD):
        assert _run_once("dead.example") is None

    assert hb.get_breaker("dead.example").state == CircuitState.OPEN


def test_ytdlp_rate_limit_failures_eventually_open_breaker(monkeypatch):
    _patch_common(monkeypatch)

    async def pool(fn, *a):
        raise RateLimitError("403")

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    for _ in range(hb._FAILURE_THRESHOLD):
        assert _run_once("blocked.example") is None

    assert hb.get_breaker("blocked.example").state == CircuitState.OPEN


def test_ytdlp_success_resets_breaker_failure_count(monkeypatch):
    _patch_common(monkeypatch)

    calls = {"n": 0}

    async def pool(fn, *a):
        calls["n"] += 1
        if calls["n"] <= hb._FAILURE_THRESHOLD - 1:
            raise RuntimeError("transient")
        return "out.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    for _ in range(hb._FAILURE_THRESHOLD - 1):
        assert _run_once("flaky.example") is None
    assert hb.get_breaker("flaky.example")._failures == hb._FAILURE_THRESHOLD - 1

    assert _run_once("flaky.example") == "out.mp4"

    breaker = hb.get_breaker("flaky.example")
    assert breaker.state == CircuitState.CLOSED
    assert breaker._failures == 0
