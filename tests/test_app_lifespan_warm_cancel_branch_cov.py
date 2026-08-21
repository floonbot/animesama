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
    def __init__(self):
        self._store = None

    def enable_persistence(self):
        return None

    def resume_pending(self):
        return None

    def _cancel_task_threadsafe(self):
        return None


def _install(monkeypatch, get_browser, fermer_browser):
    purge_done = threading.Event()

    def _noop(*a, **k):
        return None

    def _purge(*a, **k):
        purge_done.set()
        return 0

    async def _close_async_client(*a, **k):
        return None

    def _kill_all(*a, **k):
        return 0

    monkeypatch.setattr(sse_mod, "capture_loop_at_startup", _noop)
    monkeypatch.setattr(sse_mod, "signal_shutdown", _noop)
    monkeypatch.setattr(queue_mod, "queue", _FakeQueue())
    monkeypatch.setattr(nm3u8dl_mod, "purge_stale_tmp_dirs", _purge)
    monkeypatch.setattr(interceptor_mod, "get_browser", get_browser)
    monkeypatch.setattr(interceptor_mod, "fermer_browser", fermer_browser)
    monkeypatch.setattr(http_client_mod, "close_async_client", _close_async_client)
    monkeypatch.setattr(proc_registry_mod, "kill_all_processes", _kill_all)
    monkeypatch.setattr(worker_mod, "shutdown", _noop)
    monkeypatch.setattr(cover_images_mod, "shutdown_covers", _noop)
    return purge_done


def test_browser_warm_is_resolved_before_browser_close(monkeypatch):
    blocker = asyncio.Event()
    captured = {}
    holder = {}

    async def _blocking_get_browser(*a, **k):
        await blocker.wait()

    async def _fermer_browser(*a, **k):
        warm = getattr(holder["app"].state, "_browser_warm", None)
        captured["warm_done_at_close"] = warm.done() if warm is not None else None

    purge_done = _install(monkeypatch, _blocking_get_browser, _fermer_browser)

    async def scenario():
        app = FastAPI()
        holder["app"] = app
        async with app_mod.lifespan(app):
            assert purge_done.wait(timeout=5) is True
            assert app.state._browser_warm.done() is False

    asyncio.run(scenario())

    assert captured["warm_done_at_close"] is True
