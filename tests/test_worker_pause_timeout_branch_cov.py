import asyncio
import threading

import engine.download.worker as worker


class _Q:
    _cancelled = None

    def __init__(self):
        self.events = []
        self._paused = threading.Event()

    def emit(self, ev, data):
        self.events.append((ev, data))

    def statut(self):
        return {}


def test_pause_ne_consomme_pas_le_budget_timeout(monkeypatch):
    monkeypatch.setattr(worker, "MAX_EPISODE_DURATION", 0.2)

    async def _fake_signal(q):
        q.events.append(("signal", {}))

    monkeypatch.setattr(worker, "_signaler_annulation_engine", _fake_signal)

    q = _Q()
    q._paused.set()

    async def scenario():
        finish = asyncio.Event()

        async def episode(*a, **k):
            await finish.wait()
            return "ok"

        monkeypatch.setattr(worker, "_traiter_un_episode", episode)

        async def liberer():
            await asyncio.sleep(0.45)
            q._paused.clear()
            finish.set()

        res, _ = await asyncio.gather(
            worker._executer_un_episode({}, 0, 1, "T", q),
            liberer(),
        )
        return res

    result = asyncio.run(scenario())

    assert result == "ok"
    assert ("signal", {}) not in q.events


def test_timeout_reel_hors_pause_reste_echoues(monkeypatch):
    monkeypatch.setattr(worker, "MAX_EPISODE_DURATION", 0.05)

    signaled = {"n": 0}

    async def _fake_signal(q):
        signaled["n"] += 1

    monkeypatch.setattr(worker, "_signaler_annulation_engine", _fake_signal)

    q = _Q()

    async def scenario():
        async def episode(*a, **k):
            await asyncio.Event().wait()

        monkeypatch.setattr(worker, "_traiter_un_episode", episode)
        return await asyncio.wait_for(
            worker._executer_un_episode({}, 0, 1, "T", q), timeout=3
        )

    result = asyncio.run(scenario())

    assert result == "echoues"
    assert signaled["n"] == 1
