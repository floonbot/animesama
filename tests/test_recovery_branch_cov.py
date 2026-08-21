import asyncio
import sqlite3
import threading

import pytest

import engine.download.store as store_mod
import engine.download.worker as worker
import engine.observability.metrics as metrics_mod
from engine.download import _runtime as runtime
from engine.download.queue import CancelToken, _set_persistence_gauge
from engine.download.store import DownloadStore


class _FakeConn:
    """sqlite connection stub: execute raises DatabaseError, close raises and is recorded."""

    def __init__(self) -> None:
        self.closed = 0

    def execute(self, *_a, **_k):
        raise sqlite3.DatabaseError("table creation exploded")

    def commit(self):
        return None

    def close(self):
        self.closed += 1
        raise sqlite3.OperationalError("close also failed")


def test_open_closes_connection_and_reraises_on_create_table_failure(tmp_path, monkeypatch):
    """_open closes the connection (swallowing a close error) then re-raises the CREATE failure."""
    fake = _FakeConn()
    monkeypatch.setattr(store_mod.sqlite3, "connect", lambda *_a, **_k: fake)

    with pytest.raises(sqlite3.DatabaseError):
        DownloadStore._open(tmp_path / "d.db")

    assert fake.closed == 1


def test_quarantine_returns_without_moving_when_os_replace_fails(tmp_path, monkeypatch):
    """When os.replace raises OSError the corrupt db is left in place and reopen re-raises."""
    db = tmp_path / "downloads.db"
    db.write_bytes(b"not a sqlite database\x00" * 200)

    def boom_replace(*_a, **_k):
        raise OSError("device busy")

    monkeypatch.setattr(store_mod.os, "replace", boom_replace)

    with pytest.raises(sqlite3.DatabaseError):
        DownloadStore(db)

    assert db.exists()
    assert not (tmp_path / "downloads.db.corrupt").exists()


def test_quarantine_moves_db_aside_and_removes_wal_and_shm_sidecars(tmp_path):
    """_quarantine renames the db to .corrupt and deletes its stale -wal/-shm sidecars."""
    db = tmp_path / "downloads.db"
    db.write_bytes(b"corrupt payload here\x00" * 200)
    wal = tmp_path / "downloads.db-wal"
    shm = tmp_path / "downloads.db-shm"
    wal.write_bytes(b"stale-wal")
    shm.write_bytes(b"stale-shm")

    DownloadStore._quarantine(db)

    assert not db.exists()
    assert (tmp_path / "downloads.db.corrupt").read_bytes() == b"corrupt payload here\x00" * 200
    assert not wal.exists()
    assert not shm.exists()


def test_quarantine_swallows_sidecar_removal_failure(tmp_path, monkeypatch):
    """A failing os.remove on a sidecar is swallowed; the db is still moved aside."""
    db = tmp_path / "downloads.db"
    db.write_bytes(b"corrupt\x00" * 200)
    (tmp_path / "downloads.db-wal").write_bytes(b"stale-wal")

    def boom_remove(*_a, **_k):
        raise OSError("sidecar locked")

    monkeypatch.setattr(store_mod.os, "remove", boom_remove)

    DownloadStore._quarantine(db)

    assert not db.exists()
    assert (tmp_path / "downloads.db.corrupt").exists()
    assert (tmp_path / "downloads.db-wal").exists()


def test_load_queue_skips_valid_json_non_dict_payload(tmp_path):
    """load_queue keeps dict rows but skips a syntactically valid JSON list/scalar payload."""
    s = DownloadStore(tmp_path / "d.db")
    try:
        with s._lock:
            s._conn.execute("INSERT INTO queue (pos, payload) VALUES (?, ?)", (0, "[]"))
            s._conn.execute("INSERT INTO queue (pos, payload) VALUES (?, ?)", (1, "5"))
            s._conn.execute(
                "INSERT INTO queue (pos, payload) VALUES (?, ?)", (2, '{"nom": "ok"}')
            )
            s._conn.commit()
        assert s.load_queue() == [{"nom": "ok"}]
    finally:
        s.close()


def test_load_history_skips_valid_json_non_dict_payload(tmp_path):
    """load_history keeps dict rows but skips a syntactically valid JSON list/scalar payload."""
    s = DownloadStore(tmp_path / "d.db")
    try:
        with s._lock:
            s._conn.execute("INSERT INTO history (payload) VALUES (?)", ("[1, 2]",))
            s._conn.execute("INSERT INTO history (payload) VALUES (?)", ("42",))
            s._conn.execute("INSERT INTO history (payload) VALUES (?)", ('{"titre": "ok"}',))
            s._conn.commit()
        assert s.load_history() == [{"titre": "ok"}]
    finally:
        s.close()


def test_set_persistence_gauge_swallows_metrics_failure(monkeypatch):
    """_set_persistence_gauge does not propagate when metrics.set_gauge raises."""

    class _Broken:
        def set_gauge(self, *_a, **_k):
            raise RuntimeError("metrics down")

    monkeypatch.setattr(metrics_mod, "metrics", _Broken())
    _set_persistence_gauge(True)


class _RecordingMetrics:
    def __init__(self) -> None:
        self.calls: list = []

    def incr(self, name, n=1):
        self.calls.append((name, n))


class _NoIncrMetrics:
    def incr(self, *_a, **_k):
        raise AssertionError("metrics.incr must not run for a non-dict entry")


class _RuntimeQueue:
    def __init__(self, current=None) -> None:
        self._cancelled = CancelToken()
        self._state_lock = threading.Lock()
        self._history: list = []
        self._store = None
        self._current = current


def test_historique_append_ajoute_l_entree_telle_quelle(monkeypatch):
    """L'entree arrive intacte dans l'historique, sans champ ajoute."""
    monkeypatch.setattr(metrics_mod, "metrics", _RecordingMetrics())
    q = _RuntimeQueue(current={"nom": "X"})
    entree = {"titre": "T", "succes": 1, "echoues": 0, "skipped": 0}

    runtime._historique_append(q, entree)

    assert q._history == [entree]
    assert set(entree) == {"titre", "succes", "echoues", "skipped"}


def test_historique_append_non_dict_entry_skips_metrics(monkeypatch):
    """A non-dict entry is appended to history yet skips the per-episode metrics block."""
    monkeypatch.setattr(metrics_mod, "metrics", _NoIncrMetrics())
    q = _RuntimeQueue()
    entree = ["not", "a", "dict"]

    runtime._historique_append(q, entree)

    assert q._history == [entree]


class _WorkerQueue:
    def __init__(self) -> None:
        self._cancelled = CancelToken()
        self._state_lock = threading.Lock()
        self._history: list = []
        self._store = None
        self.events: list = []

    def emit(self, ev, data):
        self.events.append((ev, data))

    def statut(self):
        return {}


def test_episode_cancel_after_success_skips_sleep_and_reloops(monkeypatch):
    """Cancel set right after a successful episode skips the inter-episode sleep, then the loop breaks."""
    eps = [
        {"titre": "X", "langue": "VF", "tag": "a"},
        {"titre": "X", "langue": "VF", "tag": "b"},
    ]
    seen: list = []
    sleeps: list = []
    q = _WorkerQueue()
    monkeypatch.setattr(metrics_mod, "metrics", _RecordingMetrics())

    async def fake_un_episode(ep, i, total, titre, qq):
        seen.append(ep["tag"])
        qq._cancelled.set()
        return "succes"

    async def fake_sleep(_d):
        sleeps.append(_d)

    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: eps)
    monkeypatch.setattr(worker, "_traiter_un_episode", fake_un_episode)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", False)

    asyncio.run(worker._traiter_episode({"episodes": eps}, q))

    assert seen == ["a"]
    assert sleeps == []
    done = [data for ev, data in q.events if ev == "anime_done"]
    assert len(done) == 1
    assert done[0]["succes"] == 1
    assert done[0]["annule"] is True
