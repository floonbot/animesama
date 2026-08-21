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


def test_preserve_flag_self_resets_and_next_item_is_cleared(store, monkeypatch):
    processed: list = []

    async def rec(item, q):
        processed.append(item["nom"])

    monkeypatch.setattr(worker, "traiter_item", rec)

    async def scenario():
        q = DownloadQueue()
        q._store = store
        q._preserve_on_stop = True
        await q.ajouter({"nom": "A"})
        await q.ajouter({"nom": "B"})
        for _ in range(400):
            await asyncio.sleep(0.005)
            if len(processed) == 2 and q._current is None:
                break
        return q

    q = asyncio.run(scenario())

    assert processed == ["A", "B"]
    assert q._preserve_on_stop is False
    assert q._store.load_current() is None
