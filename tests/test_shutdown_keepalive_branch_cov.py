import asyncio
import threading

from fastapi import FastAPI

import engine.auth.manager as mgr_mod
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
        pass

    def resume_pending(self):
        pass

    def _cancel_task_threadsafe(self):
        pass


def test_lifespan_shutdown_stops_keepalive(monkeypatch):
    purge_done = threading.Event()

    async def _aget_browser(*a, **k):
        return None

    async def _afermer(*a, **k):
        return None

    async def _aclose(*a, **k):
        return None

    def _purge(*a, **k):
        purge_done.set()
        return 0

    monkeypatch.setattr(sse_mod, "capture_loop_at_startup", lambda *a, **k: None)
    monkeypatch.setattr(sse_mod, "signal_shutdown", lambda *a, **k: None)
    monkeypatch.setattr(queue_mod, "queue", _FakeQueue())
    monkeypatch.setattr(nm3u8dl_mod, "purge_stale_tmp_dirs", _purge)
    monkeypatch.setattr(interceptor_mod, "get_browser", _aget_browser)
    monkeypatch.setattr(interceptor_mod, "fermer_browser", _afermer)
    monkeypatch.setattr(http_client_mod, "close_async_client", _aclose)
    monkeypatch.setattr(proc_registry_mod, "kill_all_processes", lambda *a, **k: 0)
    monkeypatch.setattr(worker_mod, "shutdown", lambda *a, **k: None)
    monkeypatch.setattr(cover_images_mod, "shutdown_covers", lambda *a, **k: None)

    calls = []
    monkeypatch.setattr(mgr_mod.auth_manager, "stop_keepalive_loop",
                        lambda: calls.append("stop_keepalive"))

    async def scenario():
        app = FastAPI()
        async with app_mod.lifespan(app):
            warm = app.state._browser_warm
            await warm
            assert purge_done.wait(timeout=5) is True

    asyncio.run(scenario())
    assert calls == ["stop_keepalive"]
