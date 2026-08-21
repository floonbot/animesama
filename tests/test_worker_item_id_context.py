import asyncio

from engine.download import worker
from engine.observability.context import get_task_id


def test_episode_with_item_id_correlates(monkeypatch):
    seen = {}

    async def fake(item, q):
        seen["tid"] = get_task_id()

    monkeypatch.setattr(worker, "_traiter_episode", fake)
    asyncio.run(worker.traiter_item({"id": "abc123", "episodes": [{"url": "u"}]}, object()))
    assert seen["tid"] == "abc123"


def test_episode_without_item_id_has_no_context(monkeypatch):
    seen = {}

    async def fake(item, q):
        seen["tid"] = get_task_id()

    monkeypatch.setattr(worker, "_traiter_episode", fake)
    asyncio.run(worker.traiter_item({"episodes": [{"url": "u"}]}, object()))
    assert seen["tid"] == ""


def test_scan_and_direct_use_item_id_when_present(monkeypatch):
    seen = {}

    async def fs(item, q):
        seen["scan"] = get_task_id()

    async def fd(item, q):
        seen["direct"] = get_task_id()

    monkeypatch.setattr(worker, "_traiter_scan", fs)
    monkeypatch.setattr(worker, "_traiter_direct", fd)
    asyncio.run(worker.traiter_item({"id": "sid456", "_scan": True}, object()))
    asyncio.run(worker.traiter_item({"id": "did789", "_direct": True}, object()))
    assert seen["scan"] == "sid456"
    assert seen["direct"] == "did789"
