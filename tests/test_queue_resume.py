import asyncio
import threading
from types import SimpleNamespace

import pytest

import engine.download.worker as worker
from engine.download._runtime import HISTORIQUE_MAX, _est_annule, _historique_append
from engine.download.queue import CancelToken, DownloadQueue
from engine.download.store import DownloadStore
from engine.observability.metrics import metrics


@pytest.fixture
def store(tmp_path):
    """A fresh temp-backed DownloadStore, closed on teardown."""
    s = DownloadStore(tmp_path / "d.db")
    yield s
    s.close()


@pytest.fixture
def reset_metrics():
    """Clear global metrics before and after to keep tests order-independent."""
    metrics.reset()
    yield metrics
    metrics.reset()


def test_load_history_cap_truncates_independently(store):
    """load_history(cap=3) returns the last 3 entries in ascending id order."""
    for i in range(10):
        store.append_history({"i": i}, cap=200)
    hist = store.load_history(cap=3)
    assert [h["i"] for h in hist] == [7, 8, 9]


def test_store_writes_after_close_are_dropped_not_corrupting(tmp_path):
    """Writes submitted after close() are silently dropped, db stays intact."""
    p = tmp_path / "d.db"
    s = DownloadStore(p)
    s.save_queue([{"a": 1}])
    s.close()
    s.save_queue([{"b": 2}])
    s.append_history({"x": 1})
    s2 = DownloadStore(p)
    assert s2.load_queue() == [{"a": 1}]
    s2.close()


def test_save_queue_preserves_order_beyond_nine_items(store):
    """pos is numeric: 12 items reload in numeric order, not lexicographic."""
    items = [{"i": i} for i in range(12)]
    store.save_queue(items)
    assert [it["i"] for it in store.load_queue()] == list(range(12))


def test_history_persists_across_instances(tmp_path):
    """A history entry written by one instance is visible from a fresh one."""
    p = tmp_path / "d.db"
    a = DownloadStore(p)
    a.append_history({"titre": "X", "succes": 1})
    a.close()
    b = DownloadStore(p)
    assert b.load_history() == [{"titre": "X", "succes": 1}]
    b.close()


def test_restore_loads_queue_from_store(store):
    """restore() repopulates the in-memory queue from persisted items."""
    store.save_queue([{"nom": "A"}, {"nom": "B"}])
    q = DownloadQueue()
    q._store = store
    q.restore()
    assert list(q._queue) == [{"nom": "A"}, {"nom": "B"}]


def test_restore_loads_history_from_store(store):
    """restore() repopulates the in-memory history from persisted entries."""
    store.append_history({"titre": "H"})
    q = DownloadQueue()
    q._store = store
    q.restore()
    assert q._history == [{"titre": "H"}]


def test_restore_empty_db_keeps_inmemory_queue(store):
    """An empty store must not clobber a live in-memory queue."""
    q = DownloadQueue()
    q._store = store
    q._queue.append({"i": 1})
    q.restore()
    assert list(q._queue) == [{"i": 1}]


def test_resume_pending_starts_worker_when_pending(store, monkeypatch):
    """With pending items and no current, resume_pending starts the worker."""
    seen = []

    async def fake_traiter(item, q):
        seen.append(item)

    monkeypatch.setattr(worker, "traiter_item", fake_traiter)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        q._queue.append({"nom": "A"})
        q.resume_pending()
        assert q._task is not None
        await q._task

    asyncio.run(scenario())
    assert seen == [{"nom": "A"}]


def test_resume_pending_no_task_when_empty(store, monkeypatch):
    """With an empty queue, resume_pending creates no worker task."""

    async def fake_traiter(item, q):
        raise AssertionError("worker should not run on empty queue")

    monkeypatch.setattr(worker, "traiter_item", fake_traiter)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        q.resume_pending()
        return q._task

    task = asyncio.run(scenario())
    assert task is None


def test_resume_pending_noop_when_current_set(store, monkeypatch):
    """resume_pending is a no-op while an item is already in progress."""

    async def fake_traiter(item, q):
        raise AssertionError("worker should not start while current is set")

    monkeypatch.setattr(worker, "traiter_item", fake_traiter)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        q._queue.append({"nom": "A"})
        q._current = {"nom": "busy"}
        q.resume_pending()
        return q._task

    task = asyncio.run(scenario())
    assert task is None


def test_ajouter_persists_and_allows_duplicates_no_dedup(store, monkeypatch):
    """Enqueue is not idempotent: the same item persisted twice appears twice."""
    gate = threading.Event()

    async def blocking_traiter(item, q):
        while not gate.is_set():
            await asyncio.sleep(0)

    monkeypatch.setattr(worker, "traiter_item", blocking_traiter)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        await q.ajouter({"nom": "A", "key": "k"})
        await q.ajouter({"nom": "A", "key": "k"})
        persisted = q._store.load_queue()
        gate.set()
        if q._task is not None:
            await q._task
        return persisted

    persisted = asyncio.run(scenario())
    assert persisted == [{"nom": "A", "key": "k"}, {"nom": "A", "key": "k"}]


def test_run_moves_inflight_item_from_queue_to_current(store, monkeypatch):
    """While running, the item leaves the persisted queue but is recoverable as 'current'."""
    observed = []

    async def fake_traiter(item, q):
        observed.append((q._store.load_queue(), q._store.load_current()))

    monkeypatch.setattr(worker, "traiter_item", fake_traiter)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        q._queue.append({"nom": "A"})
        await q._run()

    asyncio.run(scenario())
    assert observed == [([], {"nom": "A"})]


def test_annuler_keeps_persisted_queue(store, monkeypatch):
    """annuler ne stoppe que l'item courant : la file survit, en mémoire et sur disque."""
    monkeypatch.setattr(
        "engine.download.methods._proc_registry.resume_all", lambda: 0
    )
    monkeypatch.setattr(
        "engine.download.methods._proc_registry.kill_all_processes", lambda: 0
    )
    q = DownloadQueue()
    q._store = store
    q._queue.extend([{"i": 0}, {"i": 1}])
    q._current = {"i": -1}
    assert q.annuler() is True
    assert list(q._queue) == [{"i": 0}, {"i": 1}]
    assert store.load_queue() == [{"i": 0}, {"i": 1}]


def test_deplacer_persists_to_disk(store):
    """deplacer durably reorders the persisted queue."""
    q = DownloadQueue()
    q._store = store
    q._queue.extend([{"i": 0}, {"i": 1}, {"i": 2}])
    assert q.deplacer(0, 2) is True
    assert store.load_queue() == [{"i": 1}, {"i": 2}, {"i": 0}]


def test_retirer_persists_to_disk(store):
    """retirer durably removes from the persisted queue."""
    q = DownloadQueue()
    q._store = store
    q._queue.extend([{"i": 1}, {"i": 2}, {"i": 0}])
    assert q.retirer(0) is True
    assert store.load_queue() == [{"i": 2}, {"i": 0}]


def test_run_cancelled_emits_dl_annule_and_metric(reset_metrics, monkeypatch):
    """A CancelledError in the worker emits dl_annule and bumps cancel metrics."""
    events = []

    async def cancelling_traiter(item, q):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "traiter_item", cancelling_traiter)

    async def scenario():
        q = DownloadQueue()
        q.subscribe(lambda ev, data: events.append((ev, data)))
        q._queue.append({"nom": "Z"})
        await q._run()

    asyncio.run(scenario())
    annule = [d for ev, d in events if ev == "dl_annule"]
    assert annule == [{"nom": "Z"}]
    snap = reset_metrics.snapshot()
    assert snap.get("items_annules") == 1
    assert snap.get("items_termines") == 1


def test_run_exception_emits_dl_erreur_and_metric(reset_metrics, monkeypatch):
    """A generic exception in the worker emits dl_erreur and bumps error metric."""
    events = []

    async def boom_traiter(item, q):
        raise Exception("boom")

    monkeypatch.setattr(worker, "traiter_item", boom_traiter)

    async def scenario():
        q = DownloadQueue()
        q.subscribe(lambda ev, data: events.append((ev, data)))
        q._queue.append({"nom": "E"})
        await q._run()

    asyncio.run(scenario())
    erreur = [d for ev, d in events if ev == "dl_erreur"]
    assert len(erreur) == 1
    assert erreur[0]["nom"] == "E"
    assert "boom" in erreur[0]["erreur"]
    assert reset_metrics.snapshot().get("items_erreur") == 1


def test_historique_append_writes_memory_store_and_metrics(reset_metrics, store):
    """_historique_append updates memory, store and success/failure metrics."""
    fake = SimpleNamespace(
        _state_lock=threading.Lock(), _history=[], _store=store
    )
    entree = {"titre": "T", "succes": 2, "echoues": 1, "skipped": 0}
    _historique_append(fake, entree)
    assert fake._history == [entree]
    assert store.load_history() == [entree]
    snap = reset_metrics.snapshot()
    assert snap.get("episodes_succes") == 2
    assert snap.get("episodes_echoues") == 1


def test_historique_append_caps_inmemory_history():
    """In-memory history is trimmed to HISTORIQUE_MAX, keeping the newest."""
    fake = SimpleNamespace(_state_lock=threading.Lock(), _history=[], _store=None)
    total = HISTORIQUE_MAX + 5
    for i in range(total):
        _historique_append(fake, {"titre": i})
    assert len(fake._history) == HISTORIQUE_MAX
    assert fake._history[-1] == {"titre": total - 1}


def test_est_annule_true_for_set_cancel_token():
    """_est_annule reads the CancelToken object API when set."""
    tok = CancelToken()
    tok.set()
    assert _est_annule(SimpleNamespace(_cancelled=tok)) is True


def test_est_annule_false_for_unset_cancel_token():
    """_est_annule returns False for a freshly created CancelToken."""
    assert _est_annule(SimpleNamespace(_cancelled=CancelToken())) is False


def test_est_annule_true_for_legacy_list():
    """_est_annule supports the legacy subscript API with a truthy element."""
    assert _est_annule(SimpleNamespace(_cancelled=[True])) is True


def test_est_annule_false_for_legacy_list():
    """_est_annule supports the legacy subscript API with a falsy element."""
    assert _est_annule(SimpleNamespace(_cancelled=[False])) is False


def test_est_annule_false_when_attribute_missing():
    """_est_annule returns False (no raise) when _cancelled is absent."""
    assert _est_annule(SimpleNamespace()) is False
