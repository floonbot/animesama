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


def test_failed_persist_during_run_does_not_requeue_completed_item(store, monkeypatch):
    store.save_queue([{"nom": "A"}])
    store._flush()

    state = {"dropped": False}
    real_save = store.save_queue

    def flaky_save(items):
        if not state["dropped"]:
            state["dropped"] = True
            return
        return real_save(items)

    monkeypatch.setattr(store, "save_queue", flaky_save)

    async def ok(item, q):
        return None

    monkeypatch.setattr(worker, "traiter_item", ok)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        q._queue.append({"nom": "A"})
        await q._run()

    asyncio.run(scenario())

    restarted = DownloadQueue()
    restarted._store = store
    restarted.restore()

    assert list(restarted._queue) == []
