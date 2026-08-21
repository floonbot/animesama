"""Regression : « ✕ Arrêter » est le bouton de la carte du téléchargement *actif*.

annuler() faisait self._queue.clear() : arrêter l'épisode en cours détruisait aussi
tous les animes que l'utilisateur avait mis en file derrière. Le worker doit
maintenant enchaîner sur l'item suivant.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

import engine.download.methods._proc_registry as proc_registry
import engine.download.worker as worker
from engine.download.queue import DownloadQueue
from engine.download.store import DownloadStore


@pytest.fixture
def proc_recorder(monkeypatch):
    calls = {"resume": 0, "kill": 0}

    monkeypatch.setattr(proc_registry, "set_pause_state", lambda actif: None)
    monkeypatch.setattr(
        proc_registry, "resume_all", lambda: calls.__setitem__("resume", calls["resume"] + 1) or 0
    )
    monkeypatch.setattr(
        proc_registry, "kill_all_processes",
        lambda: calls.__setitem__("kill", calls["kill"] + 1) or 0,
    )
    return SimpleNamespace(calls=calls)


@pytest.fixture
def store(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    yield s
    s.close()


def test_annuler_conserve_la_file_en_attente(proc_recorder):
    q = DownloadQueue()
    q._current = {"nom": "C"}
    q._queue.extend([{"i": 0}, {"i": 1}])

    assert q.annuler() is True

    assert [it["i"] for it in q._queue] == [0, 1]
    assert q._cancelled.is_cancelled() is True


def test_annuler_conserve_la_file_persistee(store, proc_recorder):
    q = DownloadQueue()
    q._store = store
    q._queue.extend([{"i": 0}, {"i": 1}])
    q._current = {"i": -1}

    assert q.annuler() is True

    assert store.load_queue() == [{"i": 0}, {"i": 1}]


def test_annuler_ne_logue_plus_d_items_abandonnes(proc_recorder, caplog):
    q = DownloadQueue()
    q._current = {"nom": "C"}
    q._queue.extend([{"i": 0}, {"i": 1}, {"i": 2}])

    with caplog.at_level(logging.INFO, logger="engine.download.queue"):
        assert q.annuler() is True

    assert not any("dropped" in rec.getMessage() for rec in caplog.records)


def test_le_worker_enchaine_sur_l_item_suivant(monkeypatch, proc_recorder):
    """Le cœur du correctif : l'annulation stoppe l'item courant, pas la boucle."""
    traites: list[int] = []

    async def fake_traiter(item, q):
        traites.append(item["i"])
        if item["i"] == 0:
            q.annuler()
            await asyncio.sleep(5)

    monkeypatch.setattr(worker, "traiter_item", fake_traiter)

    q = DownloadQueue()
    q._queue.extend([{"i": 0}, {"i": 1}])

    async def scenario():
        q._start_worker()
        await asyncio.wait_for(q._task, timeout=5)

    asyncio.run(scenario())

    assert traites == [0, 1]


def test_route_annuler_de_bout_en_bout(client, monkeypatch, proc_recorder):
    """Contre-épreuve HTTP : POST /api/download/annuler sur la vraie file."""
    from engine.download.queue import queue as vraie_queue

    monkeypatch.setattr(vraie_queue, "_store", None)
    monkeypatch.setattr(vraie_queue, "_current", {"nom": "En cours"})
    monkeypatch.setattr(
        vraie_queue, "_queue", type(vraie_queue._queue)([{"nom": "A"}, {"nom": "B"}])
    )

    r = client.post("/api/download/annuler", headers={"origin": "http://localhost:7843"})

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert [it["nom"] for it in vraie_queue._queue] == ["A", "B"]
    assert [it["nom"] for it in r.json()["statut"]["queue"]] == ["A", "B"]


def test_annulation_tardive_n_atteint_pas_l_item_suivant(monkeypatch, proc_recorder):
    """Le cancel traverse la boucle : s'il arrive après la fin de l'item annulé,
    il ne doit pas tuer celui d'après."""
    traites: list[int] = []

    async def fake_traiter(item, q):
        traites.append(item["i"])
        if item["i"] == 0:
            q._cancelled.set()
            q._cancel_current_item_threadsafe()
        else:
            await asyncio.sleep(0.05)

    monkeypatch.setattr(worker, "traiter_item", fake_traiter)

    q = DownloadQueue()
    q._queue.extend([{"i": 0}, {"i": 1}])

    async def scenario():
        q._start_worker()
        await asyncio.wait_for(q._task, timeout=5)

    asyncio.run(scenario())

    assert traites == [0, 1]
    assert q._history == [] or all(isinstance(h, dict) for h in q._history)
