"""Deux chemins d'annulation coexistaient dans _traiter_episode :

- la boucle sort sur _est_annule → historique + anime_done émis ;
- la tâche est cancel()ée (le vrai chemin du bouton ✕) → la CancelledError
  traverse la fonction, l'historique n'est jamais écrit et les tâches de
  prefetch déjà lancées restent en vie.

Les deux doivent clôturer l'anime de la même façon.
"""

import asyncio

import pytest

import engine.download.worker as worker
from engine.download.queue import CancelToken


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self._history: list = []
        self._current = None
        self._store = None
        self._state_lock = None
        self.events: list = []

    def emit(self, event, data):
        self.events.append((event, data))

    def statut(self):
        return {}


def _eps(n):
    return [
        {"titre": "Show", "saison": 1, "episode": i + 1, "langue": "VOSTFR",
         "url": f"https://s/ep{i}"}
        for i in range(n)
    ]


def _anime_done(q):
    return [d for ev, d in q.events if ev == "anime_done"]


def test_annulation_par_cancel_ecrit_l_historique(monkeypatch):
    q = FakeQueue()

    async def _un_episode(ep, i, total, titre, queue):
        if i == 0:
            return "succes"
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "_executer_un_episode", _un_episode)
    monkeypatch.setattr(worker, "_pause_anti_ban", lambda q: asyncio.sleep(0))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker._traiter_episode({"episodes": _eps(3)}, q))

    done = _anime_done(q)
    assert done, "anime_done doit être émis même quand la tâche est annulée"
    assert done[-1]["annule"] is True
    assert done[-1]["succes"] == 1
    assert q._history and q._history[-1]["annule"] is True


def test_annulation_par_cancel_tue_les_taches_de_prefetch(monkeypatch):
    q = FakeQueue()
    restantes: list[int] = []

    async def _prefetch_sans_fin(ep, queue):
        await asyncio.sleep(300)

    async def _un_episode(ep, i, total, titre, queue):
        if i == 0:
            return "succes"
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", True)
    monkeypatch.setattr(worker, "prefetch_extraction", _prefetch_sans_fin)
    monkeypatch.setattr(worker, "_executer_un_episode", _un_episode)
    monkeypatch.setattr(worker, "_pause_anti_ban", lambda q: asyncio.sleep(0))
    monkeypatch.setattr("engine.download._rate_limiter.cooldown_global", lambda: 0)

    async def scenario():
        try:
            await worker._traiter_episode({"episodes": _eps(3)}, q)
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        # Mesuré dans la boucle : asyncio.run() annule les tâches restantes
        # à la fermeture, ce qui masquerait la fuite après coup.
        restantes.append(
            sum(
                1
                for t in asyncio.all_tasks()
                if t is not asyncio.current_task() and not t.done()
            )
        )

    asyncio.run(scenario())

    assert restantes == [0], "les tâches de prefetch doivent être annulées avec l'anime"


def test_fin_normale_inchangee(monkeypatch):
    q = FakeQueue()

    async def _un_episode(ep, i, total, titre, queue):
        return "succes"

    monkeypatch.setattr(worker, "_executer_un_episode", _un_episode)
    monkeypatch.setattr(worker, "_pause_anti_ban", lambda q: asyncio.sleep(0))

    asyncio.run(worker._traiter_episode({"episodes": _eps(2)}, q))

    done = _anime_done(q)
    assert len(done) == 1
    assert done[-1]["succes"] == 2
    assert done[-1]["annule"] is False
    assert len(q._history) == 1
