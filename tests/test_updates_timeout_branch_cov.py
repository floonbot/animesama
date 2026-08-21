"""Regression: a favorited+downloaded anime whose online fetch timed out was
returned as None by _check_un_anime, indistinguishable from "no new episode",
so the library check reported a confident "À jour" while silently dropping the
anime (real symptom: a downloaded+favorited title with a fresh episode on the
site never surfaced). The check now (a) gives each anime the same budget as
get_episodes_async's own internal timeout instead of a tighter 30s cap, and
(b) counts timeouts/errors in `non_verifies` so the UI stops claiming "À jour"
when animes could not actually be verified.

Order-safe: the updates TTL cache is invalidated before/after; every boundary
goes through monkeypatch (auto-reverted).
"""

import asyncio

import pytest

import engine.auth.manager as auth_mod
import engine.library.scanner as scanner_mod
import engine.library.updates as updates
import engine.scraping.scraper as scraper_mod


@pytest.fixture(autouse=True)
def _reset_updates_cache():
    updates.invalider_cache_updates()
    yield
    updates.invalider_cache_updates()


def _run(coro):
    return asyncio.run(coro)


def _async_return(value):
    async def _coro(*a, **k):
        return value
    return _coro


def _patch(monkeypatch, *, librairie, favoris, get_eps):
    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", True)
    monkeypatch.setattr(scanner_mod, "scan_librairie_sync", lambda: librairie)
    monkeypatch.setattr(scraper_mod, "get_favorites_async", _async_return(favoris))
    monkeypatch.setattr(scraper_mod, "get_episodes_async", get_eps)


def _un_anime_local():
    return {"animes": [{
        "nom": "I Became a Legend",
        "saisons": [{"nom": "Saison 01", "episodes": [
            {"nom": "I Became a Legend - S01E001 VOSTFR"},
            {"nom": "I Became a Legend - S01E002 VOSTFR"},
        ]}],
    }]}


def test_timeout_anime_reported_non_verifie_not_a_jour(monkeypatch):
    async def _timeout(url, force_refresh=False):
        raise TimeoutError

    _patch(
        monkeypatch,
        librairie=_un_anime_local(),
        favoris=[{"nom": "I Became a Legend", "url": "http://site/legend"}],
        get_eps=_timeout,
    )
    out = _run(updates.check_updates_async(refresh=True))
    assert out["total_nouveaux"] == 0
    assert out["animes"] == []
    assert out["non_verifies"] == 1


def test_error_anime_reported_non_verifie(monkeypatch):
    async def _boom(url, force_refresh=False):
        raise RuntimeError("network down")

    _patch(
        monkeypatch,
        librairie=_un_anime_local(),
        favoris=[{"nom": "I Became a Legend", "url": "http://site/legend"}],
        get_eps=_boom,
    )
    out = _run(updates.check_updates_async(refresh=True))
    assert out["animes"] == []
    assert out["non_verifies"] == 1


def test_new_episode_still_detected_and_non_verifies_zero(monkeypatch):
    async def _eps(url, force_refresh=False):
        return {"titre": "I Became a Legend", "episodes": [
            {"saison": 1, "episode": 1, "url": "u1", "langue": "VOSTFR", "saison_nom": "Saison 1"},
            {"saison": 1, "episode": 2, "url": "u2", "langue": "VOSTFR", "saison_nom": "Saison 1"},
            {"saison": 1, "episode": 3, "url": "u3", "langue": "VOSTFR", "saison_nom": "Saison 1"},
        ]}

    _patch(
        monkeypatch,
        librairie=_un_anime_local(),
        favoris=[{"nom": "I Became a Legend", "url": "http://site/legend"}],
        get_eps=_eps,
    )
    out = _run(updates.check_updates_async(refresh=True))
    assert out["non_verifies"] == 0
    assert out["total_nouveaux"] == 1
    assert out["animes"][0]["nouveaux_episodes"][0]["episode"] == 3


def test_mixed_one_new_one_timeout(monkeypatch):
    librairie = {"animes": [
        {"nom": "Legend", "saisons": [{"nom": "Saison 01", "episodes": [
            {"nom": "Legend - S01E002 VOSTFR"}]}]},
        {"nom": "Slime", "saisons": [{"nom": "Saison 01", "episodes": [
            {"nom": "Slime - S01E010 VOSTFR"}]}]},
    ]}
    favoris = [
        {"nom": "Legend", "url": "http://site/legend"},
        {"nom": "Slime", "url": "http://site/slime"},
    ]

    async def _eps(url, force_refresh=False):
        if url.endswith("/legend"):
            raise TimeoutError
        return {"titre": "Slime", "episodes": [
            {"saison": 1, "episode": 11, "url": "s11", "langue": "VOSTFR", "saison_nom": "Saison 1"},
        ]}

    _patch(monkeypatch, librairie=librairie, favoris=favoris, get_eps=_eps)
    out = _run(updates.check_updates_async(refresh=True))
    assert out["total_nouveaux"] == 1
    assert out["non_verifies"] == 1
    assert [a["nom"] for a in out["animes"]] == ["Slime"]
