import asyncio
import importlib.util
import logging
import types

import pytest
from fastapi import FastAPI

import engine.cache.cover_images as cover_images_mod
import engine.download.interceptor as interceptor_mod
import engine.download.methods._proc_registry as proc_registry_mod
import engine.download.methods.nm3u8dl as nm3u8dl_mod
import engine.download.queue as queue_mod
import engine.download.worker as worker_mod
import engine.library.scanner as scanner_mod
import engine.observability.metrics as metrics_mod
import engine.scraping.http_client as http_client_mod
import web.api.app as app_mod
import web.api.routes.health as health_mod
import web.api.routes.sse as sse_mod
from engine.observability.metrics import metrics


@pytest.fixture(autouse=True)
def _snapshot_sse_globals():
    saved = (
        sse_mod._main_loop,
        sse_mod._shutdown_event,
        dict(sse_mod._listeners),
        dict(sse_mod._last_full_warn),
    )
    yield
    sse_mod._main_loop = saved[0]
    sse_mod._shutdown_event = saved[1]
    with sse_mod._listeners_lock:
        sse_mod._listeners.clear()
        sse_mod._listeners.update(saved[2])
    sse_mod._last_full_warn.clear()
    sse_mod._last_full_warn.update(saved[3])


class _Sink:
    def __init__(self):
        self.events = []

    async def __call__(self, scope, receive, send):
        self.events.append(scope.get("type"))


def test_gzip_except_sse_uses_plain_for_sse_path():
    plain = _Sink()
    wrapper = app_mod.GZipExceptSSE(plain, minimum_size=500)
    scope = {"type": "http", "path": app_mod.SSE_PATH}

    async def _recv():
        return {}

    async def _send(_m):
        return None

    asyncio.run(wrapper(scope, _recv, _send))
    assert plain.events == ["http"]


def test_host_guard_passes_through_non_http_scope():
    guard_cls = app_mod._host_guard_factory(frozenset(), frozenset())
    inner = _Sink()
    guard = guard_cls(inner)
    scope = {"type": "websocket"}

    async def _recv():
        return {}

    async def _send(_m):
        return None

    asyncio.run(guard(scope, _recv, _send))
    assert inner.events == ["websocket"]


def test_cached_static_default_cache_control_for_unknown_ext(tmp_path):
    from fastapi.testclient import TestClient

    (tmp_path / "data.txt").write_text("hello", encoding="utf-8")
    app = FastAPI()
    app.mount("/", app_mod.CachedStaticFiles(directory=str(tmp_path), html=True), name="static")
    c = TestClient(app)
    r = c.get("/data.txt")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=300"


class _FakeQueueBase:
    def __init__(self):
        self._store = None

    def enable_persistence(self):
        pass

    def resume_pending(self):
        pass

    def _cancel_task_threadsafe(self):
        pass


def _install_baseline(monkeypatch, fake_queue):
    monkeypatch.setattr(sse_mod, "capture_loop_at_startup", lambda: None)
    monkeypatch.setattr(sse_mod, "signal_shutdown", lambda: None)
    monkeypatch.setattr(queue_mod, "queue", fake_queue)

    def _purge(*a, **k):
        return 0

    async def _get_browser(*a, **k):
        return None

    async def _fermer_browser(*a, **k):
        return None

    async def _close_async_client(*a, **k):
        return None

    def _kill_all(*a, **k):
        return 0

    monkeypatch.setattr(nm3u8dl_mod, "purge_stale_tmp_dirs", _purge)
    monkeypatch.setattr(interceptor_mod, "get_browser", _get_browser)
    monkeypatch.setattr(interceptor_mod, "fermer_browser", _fermer_browser)
    monkeypatch.setattr(http_client_mod, "close_async_client", _close_async_client)
    monkeypatch.setattr(proc_registry_mod, "kill_all_processes", _kill_all)
    monkeypatch.setattr(worker_mod, "shutdown", lambda: None)
    monkeypatch.setattr(cover_images_mod, "shutdown_covers", lambda: None)


def test_lifespan_purge_thread_import_failure_logged(monkeypatch, caplog):
    monkeypatch.delattr(nm3u8dl_mod, "purge_stale_tmp_dirs", raising=True)
    fake_queue = _FakeQueueBase()
    monkeypatch.setattr(sse_mod, "capture_loop_at_startup", lambda: None)
    monkeypatch.setattr(sse_mod, "signal_shutdown", lambda: None)
    monkeypatch.setattr(queue_mod, "queue", fake_queue)

    async def _get_browser(*a, **k):
        return None

    async def _fermer_browser(*a, **k):
        return None

    async def _close_async_client(*a, **k):
        return None

    monkeypatch.setattr(interceptor_mod, "get_browser", _get_browser)
    monkeypatch.setattr(interceptor_mod, "fermer_browser", _fermer_browser)
    monkeypatch.setattr(http_client_mod, "close_async_client", _close_async_client)
    monkeypatch.setattr(proc_registry_mod, "kill_all_processes", lambda: 0)
    monkeypatch.setattr(worker_mod, "shutdown", lambda: None)
    monkeypatch.setattr(cover_images_mod, "shutdown_covers", lambda: None)

    with caplog.at_level(logging.DEBUG, logger="web.api.app"):
        async def scenario():
            app = FastAPI()
            async with app_mod.lifespan(app):
                warm = getattr(app.state, "_browser_warm", None)
                if warm is not None:
                    await asyncio.gather(warm, return_exceptions=True)
        asyncio.run(scenario())

    assert any("Nettoyage des dossiers de reprise" in r.getMessage() for r in caplog.records)


def test_lifespan_warm_browser_inner_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()

    async def _boom_browser(*a, **k):
        raise RuntimeError("warm boom")

    _install_baseline(monkeypatch, fake_queue)
    monkeypatch.setattr(interceptor_mod, "get_browser", _boom_browser)

    with caplog.at_level(logging.WARNING, logger="web.api.app"):
        async def scenario():
            app = FastAPI()
            async with app_mod.lifespan(app):
                await asyncio.gather(app.state._browser_warm, return_exceptions=True)
        asyncio.run(scenario())

    assert any("Démarrage navigateur" in r.getMessage() for r in caplog.records)


def test_lifespan_warm_browser_outer_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()
    _install_baseline(monkeypatch, fake_queue)
    monkeypatch.delattr(interceptor_mod, "get_browser", raising=True)

    with caplog.at_level(logging.WARNING, logger="web.api.app"):
        async def scenario():
            app = FastAPI()
            async with app_mod.lifespan(app):
                warm = getattr(app.state, "_browser_warm", None)
                if warm is not None:
                    await asyncio.gather(warm, return_exceptions=True)
        asyncio.run(scenario())

    assert any("Démarrage navigateur" in r.getMessage() for r in caplog.records)


def test_lifespan_signal_shutdown_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()
    _install_baseline(monkeypatch, fake_queue)

    def _boom_signal():
        raise RuntimeError("signal boom")

    monkeypatch.setattr(sse_mod, "signal_shutdown", _boom_signal)

    with caplog.at_level(logging.DEBUG, logger="web.api.app"):
        _run_lifespan_with_install_already_done(monkeypatch)

    assert any("signal_shutdown" in r.getMessage() for r in caplog.records)


def _run_lifespan_with_install_already_done(monkeypatch):
    async def scenario():
        app = FastAPI()
        async with app_mod.lifespan(app):
            warm = getattr(app.state, "_browser_warm", None)
            if warm is not None:
                await asyncio.gather(warm, return_exceptions=True)
        return app

    return asyncio.run(scenario())


def test_lifespan_cancel_task_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()

    def _boom_cancel():
        raise RuntimeError("cancel boom")

    fake_queue._cancel_task_threadsafe = _boom_cancel
    _install_baseline(monkeypatch, fake_queue)

    with caplog.at_level(logging.DEBUG, logger="web.api.app"):
        _run_lifespan_with_install_already_done(monkeypatch)

    assert any("cancel worker" in r.getMessage() for r in caplog.records)


def test_lifespan_kill_all_nonzero_logs_info(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()
    _install_baseline(monkeypatch, fake_queue)
    monkeypatch.setattr(proc_registry_mod, "kill_all_processes", lambda: 3)

    with caplog.at_level(logging.INFO, logger="web.api.app"):
        _run_lifespan_with_install_already_done(monkeypatch)

    assert any("subprocess de téléchargement tué" in r.getMessage() for r in caplog.records)


def test_lifespan_kill_all_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()
    _install_baseline(monkeypatch, fake_queue)

    def _boom_kill():
        raise RuntimeError("kill boom")

    monkeypatch.setattr(proc_registry_mod, "kill_all_processes", _boom_kill)

    with caplog.at_level(logging.DEBUG, logger="web.api.app"):
        _run_lifespan_with_install_already_done(monkeypatch)

    assert any("kill_all_processes" in r.getMessage() for r in caplog.records)


def test_lifespan_worker_shutdown_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()
    _install_baseline(monkeypatch, fake_queue)

    def _boom_worker():
        raise RuntimeError("worker boom")

    monkeypatch.setattr(worker_mod, "shutdown", _boom_worker)

    with caplog.at_level(logging.DEBUG, logger="web.api.app"):
        _run_lifespan_with_install_already_done(monkeypatch)

    assert any("worker_shutdown" in r.getMessage() for r in caplog.records)


def test_lifespan_close_async_client_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()
    _install_baseline(monkeypatch, fake_queue)

    async def _boom_close(*a, **k):
        raise RuntimeError("close boom")

    monkeypatch.setattr(http_client_mod, "close_async_client", _boom_close)

    with caplog.at_level(logging.DEBUG, logger="web.api.app"):
        _run_lifespan_with_install_already_done(monkeypatch)

    assert any("close_async_client" in r.getMessage() for r in caplog.records)


def test_lifespan_store_close_called_and_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()
    closed = {"n": 0}

    class _Store:
        def close(self):
            closed["n"] += 1
            raise RuntimeError("store boom")

    fake_queue._store = _Store()
    _install_baseline(monkeypatch, fake_queue)

    with caplog.at_level(logging.DEBUG, logger="web.api.app"):
        _run_lifespan_with_install_already_done(monkeypatch)

    assert closed["n"] == 1
    assert any("store close" in r.getMessage() for r in caplog.records)


def test_lifespan_shutdown_covers_failure_logged(monkeypatch, caplog):
    fake_queue = _FakeQueueBase()
    _install_baseline(monkeypatch, fake_queue)

    def _boom_covers():
        raise RuntimeError("covers boom")

    monkeypatch.setattr(cover_images_mod, "shutdown_covers", _boom_covers)

    with caplog.at_level(logging.DEBUG, logger="web.api.app"):
        _run_lifespan_with_install_already_done(monkeypatch)

    assert any("shutdown_covers" in r.getMessage() for r in caplog.records)


def test_update_clients_gauge_swallows_metrics_error(monkeypatch, caplog):
    def _boom_set_gauge(name, value):
        raise RuntimeError("gauge boom")

    monkeypatch.setattr(metrics, "set_gauge", _boom_set_gauge)

    with caplog.at_level(logging.DEBUG, logger="web.api.sse"):
        sse_mod._update_clients_gauge()

    assert any("metrics update failed (sse_clients)" in r.getMessage() for r in caplog.records)


def test_capture_loop_no_running_loop_warns(caplog):
    sse_mod._main_loop = None
    sse_mod._shutdown_event = None
    with caplog.at_level(logging.WARNING, logger="web.api.sse"):
        sse_mod.capture_loop_at_startup()
    assert sse_mod._main_loop is None
    assert any("no running loop at startup" in r.getMessage() for r in caplog.records)


def test_capture_loop_clears_listeners_on_loop_change():
    async def scenario():
        sentinel_loop = object()
        sse_mod._main_loop = sentinel_loop
        with sse_mod._listeners_lock:
            sse_mod._listeners[999] = asyncio.Queue()
        sse_mod.capture_loop_at_startup()
        with sse_mod._listeners_lock:
            still_there = 999 in sse_mod._listeners
        return still_there, sse_mod._main_loop is sentinel_loop

    cleared, changed = asyncio.run(scenario())
    assert cleared is False
    assert changed is False


def test_request_shutdown_swallows_call_soon_runtimeerror():
    class _DeadLoop:
        def call_soon_threadsafe(self, cb):
            raise RuntimeError("loop closed")

    async def scenario():
        sse_mod._main_loop = _DeadLoop()
        sse_mod._shutdown_event = asyncio.Event()
        sse_mod.request_shutdown()

    asyncio.run(scenario())


class _FakeRequestStays:
    async def is_disconnected(self):
        return False


def test_events_sets_main_loop_when_none():
    async def scenario():
        sse_mod._main_loop = None
        sse_mod._shutdown_event = None
        resp = await sse_mod.events(_FakeRequestStays())
        assert sse_mod._main_loop is asyncio.get_running_loop()
        agen = resp.body_iterator
        await agen.aclose()

    asyncio.run(scenario())


def test_events_breaks_on_stop_task_completion():
    async def scenario():
        sse_mod.capture_loop_at_startup()
        resp = await sse_mod.events(_FakeRequestStays())
        agen = resp.body_iterator
        await agen.__anext__()
        await agen.__anext__()
        await agen.__anext__()

        async def _delayed_set():
            await asyncio.sleep(0.02)
            sse_mod._shutdown_event.set()

        setter = asyncio.ensure_future(_delayed_set())
        ended = False
        try:
            for _ in range(4):
                await asyncio.wait_for(agen.__anext__(), timeout=3)
        except StopAsyncIteration:
            ended = True
        await asyncio.gather(setter, return_exceptions=True)
        with sse_mod._listeners_lock:
            cleaned = sse_mod._listeners == {}
        return ended, cleaned

    ended, cleaned = asyncio.run(scenario())
    assert ended is True
    assert cleaned is True


def test_emit_wraps_non_dict_data():
    captured = {}

    class _RecordingQueue:
        def put_nowait(self, item):
            captured["item"] = item

    async def scenario():
        sse_mod.capture_loop_at_startup()
        with sse_mod._listeners_lock:
            sse_mod._listeners[424242] = _RecordingQueue()
        sse_mod.emit("custom", "not-a-dict")
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert '"value": "not-a-dict"' in captured["item"]


def test_emit_swallows_metrics_error_in_push(monkeypatch, caplog):
    def _boom_incr(name, n=1):
        raise RuntimeError("incr boom")

    monkeypatch.setattr(metrics, "incr", _boom_incr)

    class _OkQueue:
        def put_nowait(self, item):
            return None

    async def scenario():
        sse_mod.capture_loop_at_startup()
        with sse_mod._listeners_lock:
            sse_mod._listeners[515151] = _OkQueue()
        with caplog.at_level(logging.DEBUG, logger="web.api.sse"):
            sse_mod.emit("queue_updated", {"a": 1})
            await asyncio.sleep(0)

    asyncio.run(scenario())
    assert any("metrics update failed (sse)" in r.getMessage() for r in caplog.records)


def test_refresh_library_on_success_swallows_import_error(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("scanner boom")

    monkeypatch.setattr(scanner_mod, "invalider_cache_librairie", _boom)

    with caplog.at_level(logging.DEBUG, logger="web.api.sse"):
        sse_mod._refresh_library_on_success("episode_done", {"succes": True, "skipped": False})

    assert any("library refresh failed" in r.getMessage() for r in caplog.records)


def test_health_keepalive_read_failure_logged(monkeypatch, caplog):
    from engine.auth.manager import auth_manager

    class _BadThread:
        @property
        def is_alive(self):
            raise RuntimeError("thread state boom")

    monkeypatch.setattr(auth_manager, "_logged_in", True, raising=False)
    monkeypatch.setattr(auth_manager, "_keepalive_thread", _BadThread(), raising=False)

    with caplog.at_level(logging.DEBUG, logger="web.api.health"):
        out = asyncio.run(health_mod.health())

    assert out["auth"]["keepalive"] is False
    assert any("health: keepalive" in r.getMessage() for r in caplog.records)


def test_health_auth_block_failure_omits_auth(monkeypatch, caplog):
    import engine.auth.manager as manager_mod

    class _BoomManager:
        @property
        def is_logged_in(self):
            raise RuntimeError("auth corrupt")

    monkeypatch.setattr(manager_mod, "auth_manager", _BoomManager())

    with caplog.at_level(logging.DEBUG, logger="web.api.health"):
        out = asyncio.run(health_mod.health())

    assert "auth" not in out
    assert any("health: auth" in r.getMessage() for r in caplog.records)


def test_health_engines_block_failure_omits_engines(monkeypatch, caplog):
    import engine.download.methods.nm3u8dl as nm

    def _boom():
        raise RuntimeError("engine boom")

    monkeypatch.setattr(nm, "_get_nm3u8dl_path", _boom)

    with caplog.at_level(logging.DEBUG, logger="web.api.health"):
        out = asyncio.run(health_mod.health())

    assert "engines" not in out
    assert any("health: engines" in r.getMessage() for r in caplog.records)


def test_health_browser_block_failure_omits_browser(monkeypatch, caplog):
    from engine.download import interceptor

    def _boom(_b):
        raise RuntimeError("browser boom")

    monkeypatch.setattr(interceptor, "_is_browser_alive", _boom)

    with caplog.at_level(logging.DEBUG, logger="web.api.health"):
        out = asyncio.run(health_mod.health())

    assert "browser" not in out
    assert any("health: browser" in r.getMessage() for r in caplog.records)


def test_health_disk_outer_block_failure(monkeypatch, caplog):
    import engine.config.settings as settings

    monkeypatch.delattr(settings, "get_downloads_dir", raising=True)

    with caplog.at_level(logging.DEBUG, logger="web.api.health"):
        out = asyncio.run(health_mod.health())

    assert out["disk"] == {}
    assert any(r.getMessage() == "health: disk" for r in caplog.records)


def test_health_uptime_block_failure(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("uptime boom")

    monkeypatch.setattr(metrics, "uptime_s", _boom)

    with caplog.at_level(logging.DEBUG, logger="web.api.health"):
        out = asyncio.run(health_mod.health())

    assert out["process"]["uptime_s"] == 0
    assert any("health: uptime" in r.getMessage() for r in caplog.records)


def test_health_psutil_process_failure_logged(monkeypatch, caplog):
    class _BadProc:
        def memory_info(self):
            raise RuntimeError("psutil boom")

    monkeypatch.setattr(health_mod, "_PROC", _BadProc())

    with caplog.at_level(logging.DEBUG, logger="web.api.health"):
        out = asyncio.run(health_mod.health())

    assert "memory_mb" not in out["process"]
    assert any("health: psutil process" in r.getMessage() for r in caplog.records)


def test_health_sse_block_failure_omits_sse(monkeypatch, caplog):
    class _BadListeners:
        def __len__(self):
            raise RuntimeError("len boom")

    monkeypatch.setattr(sse_mod, "_listeners", _BadListeners())

    with caplog.at_level(logging.DEBUG, logger="web.api.health"):
        out = asyncio.run(health_mod.health())

    assert "sse" not in out
    assert any("health: sse" in r.getMessage() for r in caplog.records)


def test_health_module_import_without_psutil():
    fake_psutil = types.ModuleType("psutil")

    def _process():
        raise RuntimeError("no psutil process")

    fake_psutil.Process = _process

    import sys

    saved = sys.modules.get("psutil")
    sys.modules["psutil"] = fake_psutil
    try:
        spec = importlib.util.spec_from_file_location("_health_no_psutil", health_mod.__file__)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["psutil"] = saved
        else:
            sys.modules.pop("psutil", None)

    assert mod._psutil is None
    assert mod._PROC is None


def test_metrics_alias_endpoint_returns_metrics():
    from web.api.routes.health import metrics_alias

    out = asyncio.run(metrics_alias())
    assert isinstance(out, dict)


def test_metrics_module_reference_is_singleton():
    assert metrics_mod.metrics is metrics
