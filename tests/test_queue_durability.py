import asyncio

import pytest

import engine.download.worker as worker
from engine.download.queue import DownloadQueue
from engine.download.store import DownloadStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "d.db"


def test_save_current_sync_is_immediately_durable(db_path):
    a = DownloadStore(db_path)
    try:
        a.save_current_sync({"nom": "A"})
        b = DownloadStore(db_path)
        try:
            assert b.load_current() == {"nom": "A"}
        finally:
            b.close()
    finally:
        a.close()


def test_save_current_sync_ignores_unserializable(db_path):
    a = DownloadStore(db_path)
    try:
        a.save_current_sync({"bad": object()})
        assert a.load_current() is None
    finally:
        a.close()


def test_run_makes_current_durable_for_external_reader(db_path, monkeypatch):
    store = DownloadStore(db_path)
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
        external = DownloadStore(db_path)
        try:
            seen = external.load_current()
        finally:
            external.close()
        release.set()
        if q._task is not None:
            await q._task
        return seen

    seen = asyncio.run(scenario())
    store.close()
    assert seen == {"nom": "A"}
