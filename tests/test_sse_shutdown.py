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


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False

def test_signal_shutdown_sets_event():
    async def scenario():
        sse.capture_loop_at_startup()
        assert sse._shutdown_event is not None
        assert sse._shutdown_event.is_set() is False
        sse.signal_shutdown()
        assert sse._shutdown_event.is_set() is True

    asyncio.run(scenario())

def test_stream_exits_on_shutdown():
    async def scenario():
        sse.capture_loop_at_startup()
        resp = await sse.events(_FakeRequest())
        agen = resp.body_iterator
        first = await agen.__anext__()
        assert "retry" in first
        await agen.__anext__()
        sse.signal_shutdown()
        await asyncio.wait_for(_drain(agen), timeout=3)
        leftover = [
            t for t in asyncio.all_tasks()
            if t is not asyncio.current_task() and not t.done()
        ]
        assert leftover == [], f"taches pending apres arret: {leftover}"

    async def _drain(agen):
        async for _ in agen:
            pass

    asyncio.run(scenario())

def test_request_shutdown_is_threadsafe_noop_without_loop():
    sse._main_loop = None
    sse._shutdown_event = None
    sse.request_shutdown()

def test_request_shutdown_sets_event_on_loop():
    async def scenario():
        sse.capture_loop_at_startup()
        assert sse._shutdown_event.is_set() is False
        sse.request_shutdown()
        await asyncio.sleep(0.05)
        assert sse._shutdown_event.is_set() is True

    asyncio.run(scenario())
