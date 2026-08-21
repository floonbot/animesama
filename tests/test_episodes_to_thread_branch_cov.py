"""Regression: the CPU-bound fiche parses (parse_panneaux/parse_saisons in
get_episodes_async, _extraire_genres in catalogue_genres_async) must run off the
event loop via asyncio.to_thread — like parse_episodes / parse_search_results
already do — otherwise they block every concurrent scraping coroutine.

Order-safe: the in-memory episode cache is snapshotted/restored; all other state
goes through monkeypatch (auto-reverted).
"""

import asyncio
import threading

import pytest

import engine.scraping.catalogue as cat_mod
import engine.scraping.episodes as ep_mod
import engine.scraping.parser as parser_mod
from engine.scraping.site.animessama import SITE_URL


class _Resp:
    text = "<html></html>"


@pytest.fixture
def _restore_ep_cache():
    cache = ep_mod.cache
    snap = dict(cache._ep)
    yield cache
    cache._ep.clear()
    cache._ep.update(snap)


def test_fiche_parses_run_off_event_loop(monkeypatch, _restore_ep_cache):
    threads: dict[str, object] = {}

    def _spy_panneaux(text):
        threads["panneaux"] = threading.current_thread()
        return []

    def _spy_saisons(text):
        threads["saisons"] = threading.current_thread()
        return []

    async def _http_get(u, cookies):
        return _Resp()

    async def _sonde(*a, **k):
        return []

    monkeypatch.setattr(ep_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    monkeypatch.setattr(ep_mod, "_lister_saisons_par_sondage", _sonde)
    monkeypatch.setattr(ep_mod._ep_disk, "get", lambda k: None)
    monkeypatch.setattr(parser_mod, "parse_panneaux", _spy_panneaux)
    monkeypatch.setattr(parser_mod, "parse_saisons", _spy_saisons)

    url = f"{SITE_URL}/catalogue/zzz-thread-slug"
    asyncio.run(ep_mod.get_episodes_async(url))

    assert threads["panneaux"] is not threading.main_thread()
    assert threads["saisons"] is not threading.main_thread()


def test_extraire_genres_runs_off_event_loop(monkeypatch):
    holder: dict[str, object] = {}

    def _spy(html):
        holder["thread"] = threading.current_thread()
        return ["Action"]

    async def _http_get(u, cookies):
        return _Resp()

    monkeypatch.setattr(cat_mod, "http_get", _http_get)
    monkeypatch.setattr(cat_mod, "_extraire_genres", _spy)

    out = asyncio.run(cat_mod.catalogue_genres_async())

    assert out == ["Action"]
    assert holder["thread"] is not threading.main_thread()
