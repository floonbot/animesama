import asyncio
import json

import pytest

import web.api.routes.sse as sse


class _FakeRequest:
    def __init__(self, disconnected: bool) -> None:
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


def _is_connected_frame(frame: str) -> bool:
    return frame == 'data: {"type": "connected"}\n\n'


def _is_snapshot_frame(frame: str) -> bool:
    return frame.startswith("event: queue_updated\ndata: ")


def test_events_disconnect_emits_initial_frames_then_ends_and_cleans_up():
    async def scenario():
        sse.capture_loop_at_startup()
        req = _FakeRequest(disconnected=True)
        resp = await sse.events(req)
        agen = resp.body_iterator

        frames = []
        ended = False
        for _ in range(6):
            try:
                frames.append(await agen.__anext__())
            except StopAsyncIteration:
                ended = True
                break

        assert ended is True
        assert frames[0] == "retry: 3000\n"
        assert _is_connected_frame(frames[1])
        assert _is_snapshot_frame(frames[2])

        snap_payload = json.loads(frames[2].split("data: ", 1)[1].strip())
        assert snap_payload["type"] == "queue_updated"
        assert "en_cours" in snap_payload
        assert "queue" in snap_payload

        assert len(frames) == 3

        with sse._listeners_lock:
            assert sse._listeners == {}

    asyncio.run(scenario())


def test_events_delivers_injected_queue_item_then_cleans_up_on_close():
    async def scenario():
        sse.capture_loop_at_startup()
        req = _FakeRequest(disconnected=False)
        resp = await sse.events(req)
        agen = resp.body_iterator

        assert (await agen.__anext__()) == "retry: 3000\n"
        assert _is_connected_frame(await agen.__anext__())
        assert _is_snapshot_frame(await agen.__anext__())

        with sse._listeners_lock:
            queues = list(sse._listeners.values())
        assert len(queues) == 1

        injected = 'data: {"type": "custom"}\n\n'
        queues[0].put_nowait(injected)

        delivered = await asyncio.wait_for(agen.__anext__(), timeout=3)
        assert delivered == injected

        await agen.aclose()

        with sse._listeners_lock:
            assert sse._listeners == {}

    asyncio.run(scenario())


def test_events_breaks_on_shutdown_after_initial_frames():
    async def scenario():
        sse.capture_loop_at_startup()
        sse.signal_shutdown()
        assert sse._shutdown_event.is_set() is True

        req = _FakeRequest(disconnected=False)
        resp = await sse.events(req)
        agen = resp.body_iterator

        frames = []
        ended = False
        for _ in range(6):
            try:
                frames.append(await asyncio.wait_for(agen.__anext__(), timeout=3))
            except StopAsyncIteration:
                ended = True
                break

        assert ended is True
        assert frames[0] == "retry: 3000\n"
        assert any(_is_connected_frame(f) for f in frames)
        assert len(frames) == 3

        with sse._listeners_lock:
            assert sse._listeners == {}

    asyncio.run(scenario())
