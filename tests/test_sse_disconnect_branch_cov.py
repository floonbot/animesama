import asyncio

import pytest

import web.api.routes.sse as sse


@pytest.fixture(autouse=True)
def _reset_sse_state():
    def _reset():
        with sse._listeners_lock:
            sse._listeners.clear()
        sse._main_loop = None
        sse._shutdown_event = None
        sse._last_full_warn.clear()

    _reset()
    yield
    _reset()


class _DisconnectAfterFirstCheck:
    def __init__(self):
        self.checks = 0

    async def is_disconnected(self):
        self.checks += 1
        return self.checks > 1


def test_stream_detects_disconnect_during_wait(monkeypatch):
    monkeypatch.setattr(sse, "PING_INTERVAL", 100)
    monkeypatch.setattr(sse, "SSE_POLL_INTERVAL", 0.05, raising=False)

    async def scenario():
        sse.capture_loop_at_startup()
        req = _DisconnectAfterFirstCheck()
        resp = await sse.events(req)
        agen = resp.body_iterator

        await agen.__anext__()
        await agen.__anext__()
        await agen.__anext__()

        async def _drain():
            async for _ in agen:
                pass

        await asyncio.wait_for(_drain(), timeout=2)
        return req.checks

    checks = asyncio.run(scenario())
    assert checks >= 2
