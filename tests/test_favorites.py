import asyncio
from types import SimpleNamespace

import pytest

from engine.scraping import favorites


class FakeCache:
    def __init__(self, fresh=False, favs=None, lock=None):
        self._fresh = fresh
        self._favs = favs if favs is not None else []
        self._lock = lock
        self.saved = None

    def fav_fresh(self):
        return self._fresh

    def get_fav(self):
        return self._favs

    def fav_lock(self):
        return self._lock

    def set_fav(self, value):
        self.saved = value


@pytest.fixture(autouse=True)
def _login(monkeypatch):
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_manager, "_logged_in", True)
    return auth_manager


def test_returns_empty_when_logged_out(monkeypatch):
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_manager, "_logged_in", False)
    monkeypatch.setattr(favorites, "cache", FakeCache(fresh=True, favs=[{"titre": "X"}]))

    async def must_not_fetch(url, cookies):
        raise AssertionError("http_get must not run when logged out")

    monkeypatch.setattr(favorites, "http_get", must_not_fetch)
    assert asyncio.run(favorites.get_favorites_async()) == []


def test_returns_cached_when_fresh(monkeypatch):
    cached = [{"titre": "Naruto"}]
    monkeypatch.setattr(favorites, "cache", FakeCache(fresh=True, favs=cached))

    async def must_not_fetch(url, cookies):
        raise AssertionError("http_get must not be called when cache is fresh")

    monkeypatch.setattr(favorites, "http_get", must_not_fetch)
    assert asyncio.run(favorites.get_favorites_async()) == cached


def test_returns_empty_when_lock_unavailable(monkeypatch):
    monkeypatch.setattr(favorites, "cache", FakeCache(fresh=False, lock=None))
    assert asyncio.run(favorites.get_favorites_async()) == []


def test_refreshes_parses_and_caches(monkeypatch):
    fake_cache = FakeCache(fresh=False, lock=asyncio.Lock())
    monkeypatch.setattr(favorites, "cache", fake_cache)

    async def fake_get(url, cookies):
        return SimpleNamespace(
            text='{"logged_in": true, "favorites": {"nom": ["Bleach"], "url": ["/catalogue/bleach"], "img": [""]}}'
        )

    monkeypatch.setattr(favorites, "http_get", fake_get)
    parsed = [{"titre": "Bleach", "slug": "bleach"}]
    monkeypatch.setattr("engine.scraping.parser.parse_favoris_api", lambda data: parsed)

    out = asyncio.run(favorites.get_favorites_async())
    assert out == parsed
    assert fake_cache.saved == parsed


def test_returns_empty_on_exception(monkeypatch):
    monkeypatch.setattr(favorites, "cache", FakeCache(fresh=False, lock=asyncio.Lock()))

    async def boom(url, cookies):
        raise RuntimeError("network down")

    monkeypatch.setattr(favorites, "http_get", boom)
    assert asyncio.run(favorites.get_favorites_async()) == []


def test_expired_session_relogin_succeeds_then_refetches(monkeypatch):
    from engine.auth.manager import auth_manager

    fake_cache = FakeCache(fresh=False, lock=asyncio.Lock())
    monkeypatch.setattr(favorites, "cache", fake_cache)
    gets = {"n": 0}
    responses = iter([
        '{"logged_in": false}',
        '{"logged_in": true, "favorites": {"nom": [], "url": [], "img": []}}',
    ])

    async def fake_get(url, cookies):
        gets["n"] += 1
        return SimpleNamespace(text=next(responses))

    monkeypatch.setattr(favorites, "http_get", fake_get)

    async def relogin_ok():
        return True

    monkeypatch.setattr(auth_manager, "re_login_if_needed", relogin_ok)
    parsed = [{"titre": "X"}]
    monkeypatch.setattr("engine.scraping.parser.parse_favoris_api", lambda data: parsed)

    out = asyncio.run(favorites.get_favorites_async())
    assert out == parsed
    assert gets["n"] == 2


def test_expired_session_relogin_failure_returns_empty(monkeypatch):
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(favorites, "cache", FakeCache(fresh=False, lock=asyncio.Lock()))

    async def fake_get(url, cookies):
        return SimpleNamespace(text='{"logged_in": false}')

    monkeypatch.setattr(favorites, "http_get", fake_get)

    async def relogin_fail():
        return False

    monkeypatch.setattr(auth_manager, "re_login_if_needed", relogin_fail)
    assert asyncio.run(favorites.get_favorites_async()) == []
