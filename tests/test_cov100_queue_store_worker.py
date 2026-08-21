import asyncio
import logging
import sqlite3
import threading
from types import SimpleNamespace

import pytest

import engine.config.settings as settings_mod
import engine.download.methods._proc_registry as proc_registry
import engine.download.queue as queue_mod
import engine.download.store as store_mod
import engine.download.worker as worker
import engine.observability.metrics as metrics_mod
from engine.download.queue import CancelToken, DownloadQueue, _item_identity
from engine.download.store import DownloadStore
from engine.observability.metrics import metrics


@pytest.fixture(autouse=True)
def _snapshot_globals():
    saved_metrics = metrics_mod.metrics
    saved_store_cls = store_mod.DownloadStore
    saved_data_dir = settings_mod.DATA_DIR
    saved_suspend = proc_registry.suspend_all
    saved_resume = proc_registry.resume_all
    saved_kill = proc_registry.kill_all_processes
    metrics.reset()
    yield
    metrics_mod.metrics = saved_metrics
    store_mod.DownloadStore = saved_store_cls
    settings_mod.DATA_DIR = saved_data_dir
    proc_registry.suspend_all = saved_suspend
    proc_registry.resume_all = saved_resume
    proc_registry.kill_all_processes = saved_kill
    metrics.reset()


class _BoomMetrics:
    def incr(self, *_a, **_k):
        raise RuntimeError("metrics down")

    def max_gauge(self, *_a, **_k):
        raise RuntimeError("metrics down")

    def resume_court(self):
        raise RuntimeError("metrics down")


def test_item_identity_falls_back_to_repr_on_unserializable():
    class _Weird:
        def __repr__(self) -> str:
            return "<weird>"

    bad = {"obj": {1, 2, 3}, "w": _Weird()}

    def _no_default(*_a, **_k):
        raise TypeError("nope")

    import json as real_json

    orig_dumps = real_json.dumps
    queue_mod.json.dumps = _no_default
    try:
        out = _item_identity(bad)
    finally:
        queue_mod.json.dumps = orig_dumps
    assert out == repr(bad)


def test_enable_persistence_success_imports_store_and_restores(tmp_path):
    settings_mod.DATA_DIR = tmp_path
    q = DownloadQueue()
    restored = []
    q.restore = lambda: restored.append(True)
    q.enable_persistence()
    assert isinstance(q._store, DownloadStore)
    assert restored == [True]
    q._store.close()


def test_enable_persistence_noop_when_store_already_set():
    q = DownloadQueue()
    sentinel = SimpleNamespace(tag="existing")
    q._store = sentinel
    called = []
    q.restore = lambda: called.append(True)
    q.enable_persistence()
    assert q._store is sentinel
    assert called == []


def test_enable_persistence_swallows_construction_failure(caplog):
    q = DownloadQueue()

    def boom():
        raise RuntimeError("cannot open db")

    store_mod.DownloadStore = boom
    with caplog.at_level(logging.WARNING, logger="engine.download.queue"):
        q.enable_persistence()
    assert q._store is None
    assert any(
        "download persistence unavailable" in rec.getMessage()
        for rec in caplog.records
    )


def test_persist_queue_swallows_store_exception():
    q = DownloadQueue()

    def boom(_items):
        raise RuntimeError("disk full")

    q._store = SimpleNamespace(save_queue=boom)
    q._queue.append({"a": 1})
    q._persist_queue()


def test_save_current_swallows_store_exception():
    q = DownloadQueue()

    def boom(_item):
        raise RuntimeError("disk full")

    q._store = SimpleNamespace(save_current=boom)
    q._save_current({"a": 1})


def test_clear_current_swallows_store_exception():
    q = DownloadQueue()

    def boom():
        raise RuntimeError("disk full")

    q._store = SimpleNamespace(clear_current=boom)
    q._clear_current()


def test_restore_returns_when_store_none():
    q = DownloadQueue()
    q._queue.append({"keep": 1})
    q.restore()
    assert list(q._queue) == [{"keep": 1}]


def test_restore_swallows_load_exception_and_returns(caplog):
    q = DownloadQueue()
    q._queue.append({"keep": 1})

    def boom():
        raise RuntimeError("db error")

    q._store = SimpleNamespace(
        load_queue=boom,
        load_history=lambda: [],
        load_current=lambda: None,
    )
    with caplog.at_level(logging.DEBUG, logger="engine.download.queue"):
        q.restore()
    assert list(q._queue) == [{"keep": 1}]


def test_ajouter_ignores_non_dict_item():
    q = DownloadQueue()

    async def go():
        return await q.ajouter(["not", "dict"])

    n = asyncio.run(go())
    assert n == 0
    assert list(q._queue) == []


def test_ajouter_swallows_metrics_failure(monkeypatch):
    q = DownloadQueue()
    monkeypatch.setattr(q, "_start_worker", lambda: None)
    metrics_mod.metrics = _BoomMetrics()

    async def go():
        return await q.ajouter({"a": 1})

    n = asyncio.run(go())
    assert n == 1
    assert list(q._queue) == [{"a": 1}]


def test_annuler_swallows_proc_registry_failure():
    q = DownloadQueue()
    q._current = {"nom": "X"}

    def boom():
        raise RuntimeError("registry down")

    proc_registry.resume_all = boom
    proc_registry.kill_all_processes = boom
    assert q.annuler() is True
    assert q._cancelled.is_cancelled() is True


def test_pause_swallows_proc_registry_failure():
    q = DownloadQueue()
    q._current = {"nom": "X"}

    def boom():
        raise RuntimeError("registry down")

    proc_registry.suspend_all = boom
    assert q.pause() is True
    assert q._paused.is_set() is True


def test_reprendre_swallows_proc_registry_failure():
    q = DownloadQueue()
    q._paused.set()

    def boom():
        raise RuntimeError("registry down")

    proc_registry.resume_all = boom
    assert q.reprendre() is True
    assert q._paused.is_set() is False


def test_run_waits_while_paused_then_processes(monkeypatch):
    q = DownloadQueue()
    q._queue.append({"nom": "A"})
    q._paused.set()
    handled = []

    async def fake_traiter(item, qq):
        handled.append(item)

    monkeypatch.setattr(worker, "traiter_item", fake_traiter)

    real_sleep = asyncio.sleep
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)
        q._paused.clear()
        await real_sleep(0)

    monkeypatch.setattr(queue_mod.asyncio, "sleep", fake_sleep)
    asyncio.run(q._run())
    assert sleeps == [0.5]
    assert handled == [{"nom": "A"}]


def test_run_cancelled_swallows_metrics_failure(monkeypatch):
    q = DownloadQueue()
    q._queue.append({"nom": "Z"})
    events = []
    q.subscribe(lambda ev, data: events.append((ev, data)))

    async def cancelling(item, qq):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "traiter_item", cancelling)
    metrics_mod.metrics = _BoomMetrics()
    asyncio.run(q._run())
    assert [d for ev, d in events if ev == "dl_annule"] == [{"nom": "Z"}]


def test_run_exception_swallows_metrics_failure(monkeypatch):
    q = DownloadQueue()
    q._queue.append({"nom": "E"})
    events = []
    q.subscribe(lambda ev, data: events.append((ev, data)))

    async def boom(item, qq):
        raise ValueError("kaboom")

    monkeypatch.setattr(worker, "traiter_item", boom)
    metrics_mod.metrics = _BoomMetrics()
    asyncio.run(q._run())
    erreur = [d for ev, d in events if ev == "dl_erreur"]
    assert len(erreur) == 1
    assert erreur[0]["nom"] == "E"


def test_run_trims_history_over_max(monkeypatch):
    q = DownloadQueue()
    q._queue.append({"nom": "A"})
    q._history = [{"i": i} for i in range(queue_mod.HISTORY_MAX + 5)]

    async def ok(item, qq):
        return None

    monkeypatch.setattr(worker, "traiter_item", ok)
    asyncio.run(q._run())
    assert len(q._history) == queue_mod.HISTORY_MAX
    assert q._history[-1] == {"i": queue_mod.HISTORY_MAX + 4}


def test_run_finally_swallows_metrics_failure(monkeypatch):
    q = DownloadQueue()
    q._queue.append({"nom": "A"})
    events = []
    q.subscribe(lambda ev, data: events.append(ev))

    async def ok(item, qq):
        return None

    monkeypatch.setattr(worker, "traiter_item", ok)
    metrics_mod.metrics = _BoomMetrics()
    asyncio.run(q._run())
    assert "queue_updated" in events


def test_store_default_path_uses_data_dir(tmp_path):
    settings_mod.DATA_DIR = tmp_path
    s = DownloadStore()
    try:
        assert (tmp_path / "downloads.db").exists()
    finally:
        s.close()


def test_load_queue_skips_non_json_rows(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    try:
        with s._lock:
            s._conn.execute("INSERT INTO queue (pos, payload) VALUES (?, ?)", (0, "not-json{"))
            s._conn.execute(
                "INSERT INTO queue (pos, payload) VALUES (?, ?)", (1, '{"nom": "ok"}')
            )
            s._conn.commit()
        assert s.load_queue() == [{"nom": "ok"}]
    finally:
        s.close()


def test_load_history_skips_non_json_rows(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    try:
        with s._lock:
            s._conn.execute("INSERT INTO history (payload) VALUES (?)", ("not-json{",))
            s._conn.execute("INSERT INTO history (payload) VALUES (?)", ('{"titre": "ok"}',))
            s._conn.commit()
        assert s.load_history() == [{"titre": "ok"}]
    finally:
        s.close()


def test_load_current_returns_none_on_non_json(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    try:
        with s._lock:
            s._conn.execute("INSERT INTO current (id, payload) VALUES (1, ?)", ("not-json{",))
            s._conn.commit()
        assert s.load_current() is None
    finally:
        s.close()


def test_close_swallows_writer_shutdown_exception(tmp_path):
    s = DownloadStore(tmp_path / "d.db")

    def boom(*_a, **_k):
        raise RuntimeError("shutdown failed")

    s._writer.shutdown = boom
    s.close()
    assert s._closed is True


def test_close_swallows_conn_close_sqlite_error(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    real_writer = s._writer
    real_writer.shutdown(wait=True)

    class _BadConn:
        def close(self):
            raise sqlite3.OperationalError("locked")

    s._conn.close()   # sans quoi la vraie connexion fuit, remplacee sans etre fermee
    s._conn = _BadConn()
    s.close()
    assert s._closed is True


class _WorkerQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self._state_lock = threading.Lock()
        self._history = []
        self._store = None
        self.events = []

    def emit(self, ev, data):
        self.events.append((ev, data))

    def statut(self):
        return {}


def _events_of(q, name):
    return [data for ev, data in q.events if ev == name]


def test_direct_on_progress_emits_episode_progress(monkeypatch, tmp_path):
    real = tmp_path / "video.mp4"
    real.write_bytes(b"x" * 4)

    async def fake_run_in_pool(fn, *args):
        on_progress = args[-1]
        on_progress(42, "downloading")
        return str(real)

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: True)

    q = _WorkerQueue()
    asyncio.run(
        worker._traiter_direct({"nom": "Film", "url_stream": "https://ok/x"}, q)
    )
    prog = _events_of(q, "episode_progress")
    assert {"pct": 42, "line": "downloading"} in prog


def test_direct_generic_exception_records_failure(monkeypatch):
    async def fake_run_in_pool(fn, *args):
        raise ValueError("V" * 500)

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: True)

    q = _WorkerQueue()
    asyncio.run(
        worker._traiter_direct({"nom": "Film", "url_stream": "https://ok/x"}, q)
    )
    done = _events_of(q, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is False
    assert done[0]["erreur"] == "V" * 200


def test_direct_reraises_cancelled_error(monkeypatch):
    async def fake_run_in_pool(fn, *args):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: True)

    q = _WorkerQueue()

    async def go():
        await worker._traiter_direct({"nom": "Film", "url_stream": "https://ok/x"}, q)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(go())
    assert _events_of(q, "episode_done") == []


def test_scan_on_progress_emits_episode_progress(monkeypatch, tmp_path):
    async def fake_run_in_pool(fn, *args):
        on_progress = args[-1]
        on_progress(10, "chap")
        return str(tmp_path / "scandir")

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr(
        "engine.library.scanner.invalider_cache_librairie", lambda: None
    )

    q = _WorkerQueue()
    item = {"nom": "Berserk", "oeuvre": "berserk", "lang": "vf", "chapitres": ["1"]}
    asyncio.run(worker._traiter_scan(item, q))
    prog = _events_of(q, "episode_progress")
    assert {"pct": 10, "line": "chap"} in prog


def test_scan_reraises_cancelled_error(monkeypatch):
    async def fake_run_in_pool(fn, *args):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)

    q = _WorkerQueue()
    item = {"nom": "Berserk", "oeuvre": "berserk", "lang": "vf", "chapitres": ["1"]}

    async def go():
        await worker._traiter_scan(item, q)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(go())
    assert _events_of(q, "episode_done") == []


def test_scan_swallows_library_invalidation_failure(monkeypatch, caplog):
    async def fake_run_in_pool(fn, *args):
        return "scandir"

    def boom():
        raise RuntimeError("scanner down")

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr(
        "engine.library.scanner.invalider_cache_librairie", boom
    )

    q = _WorkerQueue()
    item = {"nom": "Berserk", "oeuvre": "berserk", "lang": "vf", "chapitres": ["1"]}
    with caplog.at_level(logging.DEBUG, logger="engine.download.worker"):
        asyncio.run(worker._traiter_scan(item, q))
    done = _events_of(q, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is True


def test_episode_reraises_cancelled_error(monkeypatch):
    """La CancelledError remonte, mais l'anime est clôturé avant : sinon le
    bouton ✕ laissait l'anime absent de l'historique."""
    eps = [{"titre": "X", "langue": "VF", "tag": "a"}]

    async def fake_un_episode(ep, i, total, titre, qq):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: eps)
    monkeypatch.setattr(worker, "_traiter_un_episode", fake_un_episode)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", False)

    q = _WorkerQueue()

    async def go():
        await worker._traiter_episode({"episodes": eps}, q)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(go())
    done = _events_of(q, "anime_done")
    assert len(done) == 1
    assert done[0]["annule"] is True
