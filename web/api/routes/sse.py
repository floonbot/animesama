import asyncio
import itertools
import json
import logging
import threading
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()
log = logging.getLogger("web.api.sse")

_listeners: dict[int, asyncio.Queue] = {}
_listeners_lock = threading.Lock()
_main_loop: asyncio.AbstractEventLoop | None = None
_id_counter = itertools.count()
_last_full_warn: dict[int, float] = {}
_shutdown_event: asyncio.Event | None = None

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
    "Content-Type": "text/event-stream; charset=utf-8",
}

PING_INTERVAL = 25
SSE_POLL_INTERVAL = 1.0
QUEUE_MAXSIZE = 200
FULL_WARN_COOLDOWN = 60

def _update_clients_gauge() -> None:
    try:
        from engine.observability.metrics import metrics
        with _listeners_lock:
            n = len(_listeners)
        metrics.set_gauge("sse_clients", n)
    except Exception:
        log.debug("metrics update failed (sse_clients)", exc_info=True)

def capture_loop_at_startup() -> None:
    global _main_loop, _shutdown_event
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("no running loop at startup")
        return
    if _main_loop is not None and _main_loop is not loop:
        with _listeners_lock:
            _listeners.clear()
    _main_loop = loop
    _shutdown_event = asyncio.Event()

def signal_shutdown() -> None:
    if _shutdown_event is not None and not _shutdown_event.is_set():
        _shutdown_event.set()

def request_shutdown() -> None:
    loop = _main_loop
    ev = _shutdown_event
    if loop is None or ev is None:
        return
    try:
        loop.call_soon_threadsafe(ev.set)
    except RuntimeError:
        pass

@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    global _main_loop
    if _main_loop is None:
        _main_loop = asyncio.get_running_loop()

    async def stream():
        listener_id = next(_id_counter)
        client_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        with _listeners_lock:
            _listeners[listener_id] = client_queue
        _update_clients_gauge()
        get_task = None
        try:
            yield "retry: 3000\n"
            yield 'data: {"type": "connected"}\n\n'
            try:
                from engine.download.queue import queue as _q
                snap = json.dumps({"type": "queue_updated", **_q.statut()})
                yield f"event: queue_updated\ndata: {snap}\n\n"
            except Exception:
                log.debug("SSE snapshot failed", exc_info=True)
            get_task = None
            waited = 0.0
            while True:
                if _shutdown_event is not None and _shutdown_event.is_set():
                    break
                if await request.is_disconnected():
                    break
                if get_task is None:
                    get_task = asyncio.ensure_future(client_queue.get())
                stop_task = (
                    asyncio.ensure_future(_shutdown_event.wait())
                    if _shutdown_event is not None
                    else None
                )
                waiters = [t for t in (get_task, stop_task) if t is not None]
                item = None
                stop = False
                poll = min(SSE_POLL_INTERVAL, PING_INTERVAL)
                try:
                    done, _ = await asyncio.wait(
                        waiters, timeout=poll, return_when=asyncio.FIRST_COMPLETED
                    )
                    if get_task in done:
                        item = get_task.result()
                        get_task = None
                        waited = 0.0
                    elif stop_task is not None and stop_task in done:
                        stop = True
                    else:
                        waited += poll
                        if waited >= PING_INTERVAL:
                            item = 'data: {"type": "ping"}\n\n'
                            waited = 0.0
                finally:
                    if stop_task is not None and not stop_task.done():
                        stop_task.cancel()
                        await asyncio.gather(stop_task, return_exceptions=True)
                if stop:
                    break
                if item is not None:
                    yield item
        except asyncio.CancelledError:
            raise
        finally:
            if get_task is not None and not get_task.done():
                get_task.cancel()
            with _listeners_lock:
                _listeners.pop(listener_id, None)
            _last_full_warn.pop(listener_id, None)
            _update_clients_gauge()

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)

def emit(event_type: str, data: dict) -> None:
    if not isinstance(data, dict):
        data = {"value": data}
    try:
        payload_json = json.dumps({"type": event_type, **data})
    except (TypeError, ValueError):
        log.warning("non-serializable SSE message for %s", event_type)
        payload_json = json.dumps({"type": "error", "message": "non serializable"})
    sse_payload = f"event: {event_type}\ndata: {payload_json}\n\n"

    loop = _main_loop
    if loop is None:
        return

    def _push() -> None:
        with _listeners_lock:
            targets = list(_listeners.items())
        sent = 0
        dropped = 0
        for listener_id, client_queue in targets:
            try:
                client_queue.put_nowait(sse_payload)
                sent += 1
            except asyncio.QueueFull:
                dropped += 1
                now = time.time()
                if now - _last_full_warn.get(listener_id, 0) > FULL_WARN_COOLDOWN:
                    log.warning("SSE queue full (slow client) — event dropped")
                    _last_full_warn[listener_id] = now
        if sent or dropped:
            try:
                from engine.observability.metrics import metrics
                if sent:
                    metrics.incr("sse_events_sent", sent)
                if dropped:
                    metrics.incr("sse_events_dropped", dropped)
            except Exception:
                log.debug("metrics update failed (sse)", exc_info=True)

    try:
        loop.call_soon_threadsafe(_push)
    except RuntimeError:
        pass

_queue_connected = False

def connect_queue() -> None:
    global _queue_connected
    if _queue_connected:
        return
    from engine.download.queue import queue

    queue.subscribe(emit)
    queue.subscribe(_refresh_library_on_success)
    _queue_connected = True

def _refresh_library_on_success(event_type: str, data: dict) -> None:
    if event_type == "anime_done":
        if not (data.get("succes") or 0):
            return
    elif event_type == "episode_done":
        if not (data.get("succes") and not data.get("skipped")):
            return
    else:
        return
    try:
        from engine.library.scanner import invalider_cache_librairie
        from engine.library.updates import invalider_cache_updates

        invalider_cache_librairie()
        invalider_cache_updates()
    except Exception:
        log.debug("library refresh failed", exc_info=True)
