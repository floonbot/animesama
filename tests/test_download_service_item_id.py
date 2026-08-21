import asyncio

from engine.services.download_service import download_service


def test_enqueue_injects_stable_item_id(monkeypatch):
    captured = {}

    async def fake_ajouter(item):
        captured["item"] = item
        return 1

    monkeypatch.setattr(download_service._queue, "ajouter", fake_ajouter)
    asyncio.run(download_service._enqueue({"foo": "bar"}))
    item = captured["item"]
    assert isinstance(item.get("id"), str)
    assert len(item["id"]) == 6


def test_enqueue_keeps_existing_id(monkeypatch):
    captured = {}

    async def fake_ajouter(item):
        captured["item"] = item
        return 1

    monkeypatch.setattr(download_service._queue, "ajouter", fake_ajouter)
    asyncio.run(download_service._enqueue({"id": "keepme", "foo": "bar"}))
    assert captured["item"]["id"] == "keepme"
