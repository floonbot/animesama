import asyncio

import pytest

import engine.download.worker as worker
from engine.download.queue import DownloadQueue
from engine.download.store import DownloadStore


@pytest.fixture
def store(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    yield s
    s.close()


def test_external_cancel_without_user_cancel_preserves_inflight_item(store, monkeypatch):
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
        q._task.cancel()
        try:
            await q._task
        except asyncio.CancelledError:
            pass
        return q._store.load_current()

    current = asyncio.run(scenario())
    assert current == {"nom": "A"}


def test_interrupted_item_not_counted_as_terminated(store, monkeypatch):
    from engine.observability.metrics import metrics
    metrics.reset()

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
        q._task.cancel()
        try:
            await q._task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    snap = metrics.snapshot()
    metrics.reset()
    assert snap.get("items_termines", 0) == 0


def test_shutdown_preserve_keeps_inflight_and_pending(store, monkeypatch):
    import engine.download.methods._proc_registry as pr
    monkeypatch.setattr(pr, "kill_all_processes", lambda: 0)
    monkeypatch.setattr(pr, "resume_all", lambda: 0)

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
        await q.ajouter({"nom": "B"})
        await started.wait()
        q.shutdown_preserve()
        try:
            await q._task
        except asyncio.CancelledError:
            pass
        return q

    q = asyncio.run(scenario())
    assert q._store.load_current() == {"nom": "A"}
    assert q._store.load_queue() == [{"nom": "B"}]
    assert q._cancelled.is_cancelled() is False


def test_user_cancel_still_drops_inflight_item(store, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    events = []

    async def blocking(item, q):
        started.set()
        await release.wait()

    monkeypatch.setattr(worker, "traiter_item", blocking)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        q.subscribe(lambda ev, data: events.append(ev))
        await q.ajouter({"nom": "A"})
        await started.wait()
        q.annuler()
        try:
            await q._task
        except asyncio.CancelledError:
            pass
        return q._store.load_current()

    current = asyncio.run(scenario())
    assert current is None
    assert "dl_annule" in events
