"""Regression: get_lecteurs_async must not poison the season cache with an empty
result. A 200 fallback page that carries no eps[] yields ({}, fetched_ok=True);
caching that {} for 600s made every episode of the season return "no lecteurs"
until the TTL expired, even after episodes.js recovered. The fix only caches a
non-empty parse, so a transient empty parse is retried on the next call.

Order-safe (pytest-randomly): the module season cache and auth cookies are
restored by an autouse fixture.
"""

import asyncio

import pytest

import engine.scraping.players as players_mod
from engine.auth.manager import auth_manager


@pytest.fixture(autouse=True)
def _isolate_season_cache(monkeypatch):
    players_mod.clear_season_cache()
    saved = auth_manager.cookies
    monkeypatch.setattr(auth_manager, "cookies", [])
    yield
    auth_manager.cookies = saved
    players_mod.clear_season_cache()


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text


_GOOD = 'var eps1=["https://a.tld/1","https://a.tld/2"]'


def test_empty_parse_is_not_cached_and_retry_recovers(monkeypatch):
    calls = {"n": 0}

    async def fake_http_get(url, cookies):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _Resp("<html>pas de tableau eps ici</html>")
        return _Resp(_GOOD)

    monkeypatch.setattr(players_mod, "http_get", fake_http_get)

    first = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1"))
    second = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1"))

    assert first == []
    assert second == [{"host": "a.tld", "src": "https://a.tld/1"}]
    assert calls["n"] == 3
