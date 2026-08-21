import asyncio
import threading

from fastapi import FastAPI

import engine.cache.cover_images as cover_images_mod
import engine.download.interceptor as interceptor_mod
import engine.download.methods._proc_registry as proc_registry_mod
import engine.download.methods.nm3u8dl as nm3u8dl_mod
import engine.download.queue as queue_mod
import engine.download.worker as worker_mod
import engine.scraping.http_client as http_client_mod
import web.api.app as app_mod
import web.api.routes.sse as sse_mod


class _FakeQueue:
    def __init__(self, calls, lock, enable_raises=False):
        self._calls = calls
        self._lock = lock
        self._enable_raises = enable_raises
        self._store = None

    def _record(self, name):
        with self._lock:
            self._calls.append(name)

    def enable_persistence(self):
        self._record("queue.enable_persistence")
        if self._enable_raises:
            raise RuntimeError("persistence boom")

    def resume_pending(self):
        self._record("queue.resume_pending")

    def _cancel_task_threadsafe(self):
        self._record("queue._cancel_task_threadsafe")


def _install(monkeypatch, calls, lock, *, enable_raises=False, fermer_raises=False):
    fake_queue = _FakeQueue(calls, lock, enable_raises=enable_raises)
    purge_done = threading.Event()

    def _rec(name):
        def _fn(*args, **kwargs):
            with lock:
                calls.append(name)
        return _fn

    def _purge(*args, **kwargs):
        with lock:
            calls.append("purge_stale_tmp_dirs")
        purge_done.set()
        return 0

    async def _get_browser(*args, **kwargs):
        with lock:
            calls.append("get_browser")

    async def _fermer_browser(*args, **kwargs):
        with lock:
            calls.append("fermer_browser")
        if fermer_raises:
            raise RuntimeError("fermer boom")

    async def _close_async_client(*args, **kwargs):
        with lock:
            calls.append("close_async_client")

    def _kill_all_processes(*args, **kwargs):
        with lock:
            calls.append("kill_all_processes")
        return 0

    monkeypatch.setattr(sse_mod, "capture_loop_at_startup", _rec("capture_loop_at_startup"))
    monkeypatch.setattr(sse_mod, "signal_shutdown", _rec("signal_shutdown"))
    monkeypatch.setattr(queue_mod, "queue", fake_queue)
    monkeypatch.setattr(nm3u8dl_mod, "purge_stale_tmp_dirs", _purge)
    monkeypatch.setattr(interceptor_mod, "get_browser", _get_browser)
    monkeypatch.setattr(interceptor_mod, "fermer_browser", _fermer_browser)
    monkeypatch.setattr(http_client_mod, "close_async_client", _close_async_client)
    monkeypatch.setattr(proc_registry_mod, "kill_all_processes", _kill_all_processes)
    monkeypatch.setattr(worker_mod, "shutdown", _rec("worker.shutdown"))
    monkeypatch.setattr(cover_images_mod, "shutdown_covers", _rec("shutdown_covers"))
    return fake_queue, purge_done


def _run_lifespan(monkeypatch, *, enable_raises=False, fermer_raises=False):
    calls = []
    lock = threading.Lock()
    _fake_queue, purge_done = _install(
        monkeypatch, calls, lock,
        enable_raises=enable_raises, fermer_raises=fermer_raises,
    )

    async def scenario():
        app = FastAPI()
        async with app_mod.lifespan(app):
            warm = app.state._browser_warm
            await warm
            assert purge_done.wait(timeout=5) is True
        return app

    app = asyncio.run(scenario())
    with lock:
        recorded = list(calls)
    return recorded, app


def test_happy_path_records_startup_then_shutdown(monkeypatch):
    recorded, app = _run_lifespan(monkeypatch)

    for name in ("capture_loop_at_startup", "queue.enable_persistence", "queue.resume_pending"):
        assert name in recorded

    for name in (
        "signal_shutdown",
        "kill_all_processes",
        "worker.shutdown",
        "fermer_browser",
        "close_async_client",
        "shutdown_covers",
    ):
        assert name in recorded

    last_startup = max(recorded.index(n) for n in
                       ("capture_loop_at_startup", "queue.enable_persistence", "queue.resume_pending"))
    first_shutdown = min(recorded.index(n) for n in
                         ("signal_shutdown", "kill_all_processes", "worker.shutdown",
                          "fermer_browser", "close_async_client", "shutdown_covers"))
    assert last_startup < first_shutdown


def test_happy_path_startup_internal_order(monkeypatch):
    recorded, _ = _run_lifespan(monkeypatch)
    assert recorded.index("capture_loop_at_startup") < recorded.index("queue.enable_persistence")
    assert recorded.index("queue.enable_persistence") < recorded.index("queue.resume_pending")


def test_happy_path_warm_browser_ran_and_state_set(monkeypatch):
    recorded, app = _run_lifespan(monkeypatch)
    assert "get_browser" in recorded
    assert app.state._browser_warm.done() is True


def test_happy_path_purge_thread_invoked(monkeypatch):
    recorded, _ = _run_lifespan(monkeypatch)
    assert "purge_stale_tmp_dirs" in recorded


def test_happy_path_cancel_task_threadsafe_called_on_exit(monkeypatch):
    recorded, _ = _run_lifespan(monkeypatch)
    assert "queue._cancel_task_threadsafe" in recorded


def test_happy_path_store_close_skipped_when_store_none(monkeypatch):
    calls = []
    lock = threading.Lock()
    fake_queue, purge_done = _install(monkeypatch, calls, lock)

    closed = {"count": 0}

    class _Store:
        def close(self):
            closed["count"] += 1

    async def scenario():
        app = FastAPI()
        async with app_mod.lifespan(app):
            await app.state._browser_warm
            assert purge_done.wait(timeout=5) is True

    asyncio.run(scenario())
    assert fake_queue._store is None
    assert closed["count"] == 0


def test_enable_persistence_exception_isolated(monkeypatch):
    recorded, app = _run_lifespan(monkeypatch, enable_raises=True)

    assert "queue.enable_persistence" in recorded
    assert "queue.resume_pending" not in recorded
    assert "get_browser" in recorded
    assert app.state._browser_warm.done() is True

    for name in (
        "signal_shutdown",
        "kill_all_processes",
        "worker.shutdown",
        "fermer_browser",
        "close_async_client",
        "shutdown_covers",
    ):
        assert name in recorded


def test_fermer_browser_exception_does_not_block_later_shutdown(monkeypatch):
    recorded, _ = _run_lifespan(monkeypatch, fermer_raises=True)

    assert "fermer_browser" in recorded
    assert "close_async_client" in recorded
    assert "shutdown_covers" in recorded
    assert recorded.index("fermer_browser") < recorded.index("close_async_client")
    assert recorded.index("close_async_client") < recorded.index("shutdown_covers")


def test_queue_singleton_untouched_without_install():
    assert isinstance(queue_mod.queue, queue_mod.DownloadQueue)
