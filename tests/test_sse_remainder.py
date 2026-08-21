import asyncio
import logging

import pytest

import web.api.routes.sse as sse


class _FakeRequest:
    def __init__(self, disconnected: bool = False) -> None:
        self._disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self._disconnected


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


def _connected_frame(frame: str) -> bool:
    return frame == 'data: {"type": "connected"}\n\n'


def _snapshot_frame(frame: str) -> bool:
    return frame.startswith("event: queue_updated\ndata: ")


def test_stream_yields_ping_when_wait_times_out(monkeypatch):
    monkeypatch.setattr(sse, "PING_INTERVAL", 0.01)

    real_wait = asyncio.wait

    async def _empty_wait(waiters, timeout=None, return_when=None):
        for t in waiters:
            t.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        return set(), set(waiters)

    async def scenario():
        sse.capture_loop_at_startup()
        resp = await sse.events(_FakeRequest(disconnected=False))
        agen = resp.body_iterator

        assert (await agen.__anext__()) == "retry: 3000\n"
        assert _connected_frame(await agen.__anext__())
        assert _snapshot_frame(await agen.__anext__())

        monkeypatch.setattr(sse.asyncio, "wait", _empty_wait)

        ping = await asyncio.wait_for(agen.__anext__(), timeout=3)
        assert ping == 'data: {"type": "ping"}\n\n'

        monkeypatch.setattr(sse.asyncio, "wait", real_wait)
        with sse._listeners_lock:
            queues = list(sse._listeners.values())
        assert len(queues) == 1
        await agen.aclose()

        with sse._listeners_lock:
            assert sse._listeners == {}

    asyncio.run(scenario())


def test_stream_skips_snapshot_when_statut_raises(monkeypatch, caplog):
    from engine.download import queue as queue_mod

    def _boom():
        raise RuntimeError("statut exploded")

    monkeypatch.setattr(queue_mod.queue, "statut", _boom)

    async def scenario():
        sse.capture_loop_at_startup()
        resp = await sse.events(_FakeRequest(disconnected=True))
        agen = resp.body_iterator

        frames = []
        ended = False
        with caplog.at_level(logging.DEBUG, logger="web.api.sse"):
            for _ in range(6):
                try:
                    frames.append(await agen.__anext__())
                except StopAsyncIteration:
                    ended = True
                    break
        return frames, ended

    frames, ended = asyncio.run(scenario())

    assert ended is True
    assert frames[0] == "retry: 3000\n"
    assert _connected_frame(frames[1])
    assert not any(_snapshot_frame(f) for f in frames)
    assert frames == ["retry: 3000\n", 'data: {"type": "connected"}\n\n']
    assert any(
        rec.levelno == logging.DEBUG and "SSE snapshot failed" in rec.getMessage()
        for rec in caplog.records
    )


def test_stream_cancels_pending_get_task_in_finally(monkeypatch):
    captured = {}

    async def scenario():
        sse.capture_loop_at_startup()
        resp = await sse.events(_FakeRequest(disconnected=False))
        agen = resp.body_iterator

        await agen.__anext__()
        await agen.__anext__()
        await agen.__anext__()

        original_ensure = asyncio.ensure_future

        def _spy_ensure(coro_or_future):
            fut = original_ensure(coro_or_future)
            name = getattr(getattr(coro_or_future, "cr_code", None), "co_name", "")
            if name == "get":
                captured["get_task"] = fut
            return fut

        monkeypatch.setattr(sse.asyncio, "ensure_future", _spy_ensure)

        task = asyncio.ensure_future(agen.__anext__())
        await asyncio.sleep(0.05)
        assert "get_task" in captured
        assert captured["get_task"].done() is False

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0.05)
        return captured["get_task"]

    get_task = asyncio.run(scenario())
    assert get_task.cancelled() is True


def test_emit_queue_full_warns_once_then_suppressed(monkeypatch, caplog):
    clock = {"now": 1000.0}
    monkeypatch.setattr(sse.time, "time", lambda: clock["now"])

    class _AlwaysFull:
        def __init__(self):
            self.attempts = 0

        def put_nowait(self, item):
            self.attempts += 1
            raise asyncio.QueueFull

    full_q = _AlwaysFull()

    async def scenario():
        sse.capture_loop_at_startup()
        with sse._listeners_lock:
            sse._listeners[7777] = full_q

        with caplog.at_level(logging.WARNING, logger="web.api.sse"):
            sse.emit("queue_updated", {"a": 1})
            await asyncio.sleep(0)
            first_warns = [
                r for r in caplog.records if "SSE queue full" in r.getMessage()
            ]
            stamp_after_first = sse._last_full_warn.get(7777)

            clock["now"] = 1000.0 + sse.FULL_WARN_COOLDOWN - 1
            caplog.clear()
            sse.emit("queue_updated", {"a": 2})
            await asyncio.sleep(0)
            within_cooldown = [
                r for r in caplog.records if "SSE queue full" in r.getMessage()
            ]

            clock["now"] = 1000.0 + sse.FULL_WARN_COOLDOWN + 1
            caplog.clear()
            sse.emit("queue_updated", {"a": 3})
            await asyncio.sleep(0)
            after_cooldown = [
                r for r in caplog.records if "SSE queue full" in r.getMessage()
            ]

        return first_warns, within_cooldown, after_cooldown, stamp_after_first

    first_warns, within_cooldown, after_cooldown, stamp = asyncio.run(scenario())

    assert len(first_warns) == 1
    assert stamp == 1000.0
    assert within_cooldown == []
    assert len(after_cooldown) == 1
    assert full_q.attempts == 3
    assert sse._last_full_warn[7777] == 1000.0 + sse.FULL_WARN_COOLDOWN + 1


def test_emit_queue_full_increments_dropped_metric():
    from engine.observability.metrics import metrics

    metrics.reset()

    class _AlwaysFull:
        def put_nowait(self, item):
            raise asyncio.QueueFull

    async def scenario():
        sse.capture_loop_at_startup()
        with sse._listeners_lock:
            sse._listeners[7777] = _AlwaysFull()
        sse.emit("queue_updated", {"a": 1})
        await asyncio.sleep(0)

    asyncio.run(scenario())
    snap = metrics.snapshot()
    assert snap.get("sse_events_dropped") == 1
    assert "sse_events_sent" not in snap
    metrics.reset()


def test_emit_increments_sent_metric_on_success():
    from engine.observability.metrics import metrics

    metrics.reset()

    class _OkQueue:
        def put_nowait(self, item):
            pass

    async def scenario():
        sse.capture_loop_at_startup()
        with sse._listeners_lock:
            sse._listeners[1] = _OkQueue()
        sse.emit("queue_updated", {"a": 1})
        await asyncio.sleep(0)

    asyncio.run(scenario())
    snap = metrics.snapshot()
    assert snap.get("sse_events_sent") == 1
    assert "sse_events_dropped" not in snap
    metrics.reset()


def test_clients_gauge_tracks_listeners():
    from engine.observability.metrics import metrics

    metrics.reset()

    async def scenario():
        sse.capture_loop_at_startup()
        resp = await sse.events(_FakeRequest(disconnected=False))
        agen = resp.body_iterator
        await agen.__anext__()
        await agen.__anext__()
        await agen.__anext__()
        during = metrics.gauges().get("sse_clients")
        await agen.aclose()
        return during, metrics.gauges().get("sse_clients")

    during, after = asyncio.run(scenario())
    assert during == 1
    assert after == 0
    metrics.reset()


def test_emit_returns_when_loop_is_none():
    delivered = {}

    class _RecordingQueue:
        def put_nowait(self, item):
            delivered["item"] = item

    q = _RecordingQueue()
    with sse._listeners_lock:
        sse._listeners[31337] = q
    assert sse._main_loop is None

    sse.emit("queue_updated", {"n": 1})

    assert "item" not in delivered


def test_emit_swallows_call_soon_threadsafe_runtimeerror(monkeypatch):
    class _DeadLoop:
        def call_soon_threadsafe(self, cb):
            raise RuntimeError("event loop is closed")

    monkeypatch.setattr(sse, "_main_loop", _DeadLoop())

    sse.emit("queue_updated", {"n": 1})


def test_request_shutdown_noop_when_event_none_but_loop_set():
    scheduled = {"calls": 0}

    class _SpyLoop:
        def call_soon_threadsafe(self, cb):
            scheduled["calls"] += 1

    sse._main_loop = _SpyLoop()
    sse._shutdown_event = None

    sse.request_shutdown()

    assert scheduled["calls"] == 0


def test_request_shutdown_noop_when_loop_none_but_event_set():
    async def scenario():
        ev = asyncio.Event()
        sse._main_loop = None
        sse._shutdown_event = ev
        sse.request_shutdown()
        await asyncio.sleep(0)
        return ev.is_set()

    was_set = asyncio.run(scenario())
    assert was_set is False


def test_signal_shutdown_noop_when_event_none():
    sse._shutdown_event = None
    sse.signal_shutdown()
    assert sse._shutdown_event is None


def test_signal_shutdown_idempotent_when_already_set():
    async def scenario():
        sse.capture_loop_at_startup()
        sse._shutdown_event.set()
        sse.signal_shutdown()
        return sse._shutdown_event.is_set()

    assert asyncio.run(scenario()) is True
