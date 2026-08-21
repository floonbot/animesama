import asyncio

import pytest

import engine.download.worker as worker
from engine.download.queue import DownloadQueue
from engine.download.store import DownloadStore


@pytest.fixture
def store(tmp_path):
    """A fresh temp-backed DownloadStore, closed on teardown."""
    s = DownloadStore(tmp_path / "d.db")
    yield s
    s.close()


def test_load_current_none_when_absent(store):
    """A store with no in-flight item returns None."""
    assert store.load_current() is None


def test_save_load_clear_current_roundtrip(store):
    """save_current persists a single in-flight item; clear_current removes it."""
    store.save_current({"nom": "A"})
    assert store.load_current() == {"nom": "A"}
    store.save_current({"nom": "B"})
    assert store.load_current() == {"nom": "B"}
    store.clear_current()
    assert store.load_current() is None


def test_inflight_item_is_persisted_as_current(store, monkeypatch):
    """While the worker processes an item, it is durably recorded as the current item."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking(item, q):
        started.set()
        await release.wait()

    monkeypatch.setattr(worker, "traiter_item", blocking)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        await q.ajouter({"nom": "A"})
        await started.wait()
        current = q._store.load_current()
        release.set()
        if q._task is not None:
            await q._task
        return current

    assert asyncio.run(scenario()) == {"nom": "A"}


def test_current_cleared_after_completion(store, monkeypatch):
    """A normally-completed item leaves no in-flight record behind."""

    async def ok(item, q):
        return None

    monkeypatch.setattr(worker, "traiter_item", ok)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        q._queue.append({"nom": "A"})
        await q._run()
        return q._store.load_current()

    assert asyncio.run(scenario()) is None


def test_restore_requeues_interrupted_current_at_front(store):
    """A crash leaves a 'current' row; restore re-enqueues it ahead of the pending queue."""
    store.save_queue([{"nom": "B"}])
    store.save_current({"nom": "A"})
    q = DownloadQueue()
    q._store = store
    q.restore()
    assert list(q._queue) == [{"nom": "A"}, {"nom": "B"}]


def test_restore_does_not_duplicate_current_already_in_queue(store):
    """If the interrupted item is still in the persisted queue, restore must not duplicate it."""
    store.save_queue([{"nom": "A"}, {"nom": "B"}])
    store.save_current({"nom": "A"})
    q = DownloadQueue()
    q._store = store
    q.restore()
    assert list(q._queue) == [{"nom": "A"}, {"nom": "B"}]


def test_restore_with_only_current_and_empty_queue(store):
    """An interrupted item with an otherwise-empty queue is recovered as the sole pending item."""
    store.save_current({"nom": "A"})
    q = DownloadQueue()
    q._store = store
    q.restore()
    assert list(q._queue) == [{"nom": "A"}]


def test_save_current_snapshots_against_later_mutation(store):
    """save_current captures a snapshot; mutating the item afterwards must not change it."""
    item = {"nom": "A", "n": 1}
    store.save_current(item)
    item["n"] = 999
    item["added"] = "later"
    assert store.load_current() == {"nom": "A", "n": 1}


def test_restore_dedups_current_by_content_regardless_of_key_order(store):
    """A current item equal in content (any key order) to a queued item is not duplicated."""
    store.save_queue([{"a": 1, "b": 2}])
    store.save_current({"b": 2, "a": 1})
    q = DownloadQueue()
    q._store = store
    q.restore()
    assert list(q._queue) == [{"a": 1, "b": 2}]


def test_restore_keeps_current_overlapping_but_unequal_queue_item(store):
    """Dedup is by FULL content: a current that shares a field but differs is still re-enqueued."""
    store.save_queue([{"nom": "A", "ep": 2}])
    store.save_current({"nom": "A", "ep": 1})
    q = DownloadQueue()
    q._store = store
    q.restore()
    assert list(q._queue) == [{"nom": "A", "ep": 1}, {"nom": "A", "ep": 2}]
