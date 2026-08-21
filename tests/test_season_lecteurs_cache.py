"""Season-page cache for get_lecteurs_async.

Downloading a multi-episode season calls get_lecteurs_async once per episode,
and every episode of a season strips to the SAME season URL (only ?ep differs).
Without a cache the identical season page is fetched + scanned once per episode.
These tests pin the behaviour-preserving cache: the second same-season call
reuses the first fetch (no extra http_get) while returning the per-episode
correct lecteurs, and the http_get seam still fires on a cold cache.

All HTML/JS fixtures are inline; http_get and auth cookies are monkeypatched.
A function-scoped autouse fixture clears the module cache so the tests are
order-independent (pytest-randomly safe).
"""

import asyncio

import pytest

import engine.scraping.players as players_mod
from engine.auth.manager import auth_manager
from engine.scraping.site.animessama import SITE_URL


@pytest.fixture(autouse=True)
def _isolate_season_cache():
    players_mod.clear_season_cache()
    saved = auth_manager.cookies
    yield
    auth_manager.cookies = saved
    players_mod.clear_season_cache()


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


def _install(monkeypatch, fake, cookies=None):
    monkeypatch.setattr(players_mod, "http_get", fake)
    monkeypatch.setattr(auth_manager, "cookies", cookies if cookies is not None else [])


_SEASON_HTML = 'var eps1=["https://a.tld/1","https://b.tld/2","https://c.tld/3"]'


def test_same_season_second_call_skips_http_get(monkeypatch):
    """Two episodes of one season => one fetch, each ep mapped correctly."""
    calls = {"n": 0}

    async def fake_http_get(url, cookies):
        calls["n"] += 1
        return _FakeResp(_SEASON_HTML)

    _install(monkeypatch, fake_http_get)

    ep1 = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1"))
    ep2 = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=2"))

    assert calls["n"] == 1
    assert ep1 == [{"host": "a.tld", "src": "https://a.tld/1"}]
    assert ep2 == [{"host": "b.tld", "src": "https://b.tld/2"}]


def test_cold_cache_still_calls_http_get(monkeypatch):
    """A cold cache must still hit the network (the http_get seam survives)."""
    calls = {"n": 0}

    async def fake_http_get(url, cookies):
        calls["n"] += 1
        return _FakeResp(_SEASON_HTML)

    _install(monkeypatch, fake_http_get)

    asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1"))
    assert calls["n"] == 1


def test_different_seasons_are_cached_independently(monkeypatch):
    """Distinct season URLs each fetch once and do not collide."""
    seen = []

    async def fake_http_get(url, cookies):
        seen.append(url)
        return _FakeResp(_SEASON_HTML)

    _install(monkeypatch, fake_http_get)

    asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1"))
    asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison2/vostfr?ep=1"))
    asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=2"))

    assert seen == [
        SITE_URL + "/catalogue/x/saison1/vostfr",
        SITE_URL + "/catalogue/x/saison2/vostfr",
    ]


def test_warm_hit_bypasses_parse_lecteurs_rescan(monkeypatch):
    """The eps[] scan (_extraire_eps_arrays) runs exactly once across a cold miss
    and a warm hit: the miss scans once (no double scan), the warm hit not at all."""
    import engine.scraping.parser._base as base_mod

    calls = {"http": 0, "scan": 0}
    real_scan = base_mod._extraire_eps_arrays

    def counting_scan(html):
        calls["scan"] += 1
        return real_scan(html)

    async def fake_http_get(url, cookies):
        calls["http"] += 1
        return _FakeResp(_SEASON_HTML)

    monkeypatch.setattr(base_mod, "_extraire_eps_arrays", counting_scan)
    _install(monkeypatch, fake_http_get)

    r1 = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1"))
    r2 = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=3"))

    assert calls["http"] == 1
    assert calls["scan"] == 1
    assert r1 == [{"host": "a.tld", "src": "https://a.tld/1"}]
    assert r2 == [{"host": "c.tld", "src": "https://c.tld/3"}]


def test_failed_fetch_is_not_cached(monkeypatch):
    """A failed fetch must not poison the cache (retry refetches). The season page
    is the first hop; unreachable, it yields nothing and caches nothing."""
    calls = {"n": 0}

    async def fake_http_get(url, cookies):
        calls["n"] += 1
        return None if calls["n"] <= 1 else _FakeResp(_SEASON_HTML)

    _install(monkeypatch, fake_http_get)

    first = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1"))
    second = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1"))

    assert first == []
    assert calls["n"] == 2
    assert second == [{"host": "a.tld", "src": "https://a.tld/1"}]
