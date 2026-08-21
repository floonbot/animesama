import asyncio

import engine.download.worker as worker


class _Q:
    _cancelled = None

    def __init__(self):
        self.events = []

    def emit(self, ev, data):
        self.events.append((ev, data))

    def statut(self):
        return {}


def test_traiter_direct_caps_runaway_download(monkeypatch):
    async def hanging(*a, **k):
        await asyncio.Event().wait()

    signaled = {"n": 0}

    async def _fake_signal(q):
        signaled["n"] += 1

    import engine.utils.security as sec

    monkeypatch.setattr(worker, "_run_in_pool", hanging)
    monkeypatch.setattr(worker, "_signaler_annulation_engine", _fake_signal)
    monkeypatch.setattr(worker, "MAX_EPISODE_DURATION", 0.05)
    monkeypatch.setattr(sec, "is_safe_url", lambda u: True)

    q = _Q()
    item = {"_direct": True, "url_stream": "https://host/x.m3u8", "nom": "Film"}

    async def scenario():
        await asyncio.wait_for(worker._traiter_direct(item, q), timeout=3)

    asyncio.run(scenario())

    done = [d for ev, d in q.events if ev == "episode_done"]
    assert done and done[-1].get("succes") is False
    assert signaled["n"] == 1
