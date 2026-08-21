import asyncio

import engine.auth.manager as mgr_mod
from engine.auth.manager import AuthManager


class FakeStorage:
    def __init__(self):
        self.credentials = None

    def load_credentials(self):
        return self.credentials


def _make_mgr(monkeypatch):
    monkeypatch.setattr(mgr_mod, "AuthStorage", FakeStorage)
    instance = AuthManager()
    monkeypatch.setattr(instance, "start_keepalive_loop", lambda: None)
    return instance


def test_login_lock_reused_within_one_loop(monkeypatch):
    mgr = _make_mgr(monkeypatch)

    async def scenario():
        first = mgr._login_lock()
        second = mgr._login_lock()
        return first, second

    first, second = asyncio.run(scenario())
    assert isinstance(first, asyncio.Lock)
    assert first is second
    assert mgr._login_lock_holder["lock"] is first


def test_re_login_serializes_login_async(monkeypatch):
    mgr = _make_mgr(monkeypatch)
    mgr.storage.credentials = {"email": "e", "password": "p"}

    state = {"current": 0, "max": 0, "calls": 0}

    async def fake_login(email, password):
        state["calls"] += 1
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        state["current"] -= 1
        return {"ok": True}

    monkeypatch.setattr(mgr, "login_async", fake_login)

    async def scenario():
        return await asyncio.gather(
            mgr.re_login_if_needed(),
            mgr.re_login_if_needed(),
        )

    results = asyncio.run(scenario())
    assert results == [True, True]
    assert state["calls"] == 2
    assert state["max"] == 1


def test_re_login_login_raises_releases_lock(monkeypatch):
    mgr = _make_mgr(monkeypatch)
    mgr.storage.credentials = {"email": "e", "password": "p"}

    outcomes = {"mode": "raise"}

    async def fake_login(email, password):
        if outcomes["mode"] == "raise":
            raise RuntimeError("boom")
        return {"ok": True}

    monkeypatch.setattr(mgr, "login_async", fake_login)

    async def scenario():
        first = await mgr.re_login_if_needed()
        outcomes["mode"] = "ok"
        second = await mgr.re_login_if_needed()
        return first, second, mgr._login_lock_holder["lock"].locked()

    first, second, still_locked = asyncio.run(scenario())
    assert first is False
    assert second is True
    assert still_locked is False
