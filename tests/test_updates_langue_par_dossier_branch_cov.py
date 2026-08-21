"""Regression: the update language filter was anime-global (langue_locale over ALL
seasons), so a library mixing languages per season (S1 VF, S2 VOSTFR) silently
dropped real updates in the minority-language season. The filter is now per-folder
(langue_locale_par_dossier), falling back to the anime-global dominant for folders
absent locally (preserves new-season behaviour).

Order-safe: the updates TTL cache is invalidated before/after; all boundaries go
through monkeypatch (auto-reverted).
"""

import asyncio

import pytest

import engine.auth.manager as auth_mod
import engine.library.scanner as scanner_mod
import engine.library.updates as updates
import engine.scraping.scraper as scraper_mod
from engine.library.updates import langue_locale_par_dossier


@pytest.fixture(autouse=True)
def _reset_updates_cache():
    updates.invalider_cache_updates()
    yield
    updates.invalider_cache_updates()


def _async_return(value):
    async def _coro(*a, **k):
        return value
    return _coro


def _patch(monkeypatch, *, librairie, favoris, episodes_by_url):
    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", True)
    monkeypatch.setattr(scanner_mod, "scan_librairie_sync", lambda: librairie)
    monkeypatch.setattr(scraper_mod, "get_favorites_async", _async_return(favoris))

    async def _get_eps(url, force_refresh=False):
        return episodes_by_url.get(url, {"episodes": []})

    monkeypatch.setattr(scraper_mod, "get_episodes_async", _get_eps)


def test_langue_locale_par_dossier_maps_each_folder():
    saisons = [
        {"nom": "Saison 01", "episodes": [{"nom": "A - S01E001 VF"}, {"nom": "A - S01E002 VF"}]},
        {"nom": "Saison 02", "episodes": [{"nom": "A - S02E001 VOSTFR"}]},
        {"nom": "", "episodes": [{"nom": "A - E001 VF"}]},
    ]
    assert langue_locale_par_dossier(saisons) == {"saison 01": "VF", "saison 02": "VOSTFR"}


def test_minority_language_season_update_surfaces(monkeypatch):
    librairie = {"animes": [{
        "nom": "Mix",
        "saisons": [
            {"nom": "Saison 01", "episodes": [
                {"nom": "Mix - S01E001 VF"},
                {"nom": "Mix - S01E002 VF"},
                {"nom": "Mix - S01E003 VF"},
            ]},
            {"nom": "Saison 02", "episodes": [{"nom": "Mix - S02E001 VOSTFR"}]},
        ],
    }]}
    favoris = [{"nom": "Mix", "url": "http://site/mix"}]
    episodes = {"http://site/mix": {"titre": "Mix", "episodes": [
        {"saison": 2, "episode": 2, "url": "vo_s2e2", "langue": "VOSTFR", "saison_nom": "Saison 2"},
        {"saison": 2, "episode": 2, "url": "vf_s2e2", "langue": "VF", "saison_nom": "Saison 2"},
    ]}}
    _patch(monkeypatch, librairie=librairie, favoris=favoris, episodes_by_url=episodes)

    out = asyncio.run(updates.check_updates_async())
    urls = {e["url"] for e in out["animes"][0]["nouveaux_episodes"]}
    assert "vo_s2e2" in urls
    assert "vf_s2e2" not in urls
