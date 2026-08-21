"""Regression for two get_episodes_async fixes:

- force_refresh now bypasses the in-memory *fiche* cache too (previously only the
  disk fiche lookup was guarded, so a warm poisoned mem[fiche_key] was served for a
  season URL despite force_refresh=True).
- the sondage merge dedups season URLs by a normalized key (strip query, trailing
  slash, case) so a fiche href differing only by a trailing slash / language case
  from the probed URL no longer re-adds the same season (duplicate episodes).

Order-safe: the in-memory episode cache is snapshotted/restored.
"""

import asyncio

import pytest

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


def test_force_refresh_bypasses_memory_fiche_cache(monkeypatch, _restore_ep_cache):
    cache = _restore_ep_cache
    url = f"{SITE_URL}/catalogue/frslug/saison1/vostfr"
    fiche_key = f"{SITE_URL}/catalogue/frslug"
    cache.set_ep(fiche_key, {"titre": "STALE", "episodes": [{"n": 99}], "langues": ["vostfr"], "total": 1})

    fresh = {"titre": "Fresh", "episodes": [{"n": 1}], "langues": ["vostfr"]}
    fresh_saisons = [{"saison": 1, "url": url, "lang": "vostfr", "_parsed": fresh}]

    async def _http_get(u, cookies):
        return _Resp()

    async def _sonde(*a, **k):
        return []

    monkeypatch.setattr(ep_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    monkeypatch.setattr(ep_mod, "_lister_saisons_par_sondage", _sonde)
    monkeypatch.setattr(ep_mod._ep_disk, "get", lambda k: None)
    monkeypatch.setattr(ep_mod._ep_disk, "set_many", lambda items: None)
    monkeypatch.setattr(parser_mod, "parse_panneaux", lambda text: [])
    monkeypatch.setattr(parser_mod, "parse_saisons", lambda text: fresh_saisons)

    out = asyncio.run(ep_mod.get_episodes_async(url, force_refresh=True))

    assert out["titre"] == "Fresh"
    assert out["episodes"] == [{"n": 1}]


def test_sondage_dedup_normalizes_url(monkeypatch, _restore_ep_cache):
    fiche = f"{SITE_URL}/catalogue/dslug"
    parsed_s = {"titre": "D", "episodes": [{"n": 1}], "langues": ["vostfr"]}
    fiche_saisons = [{
        "saison": 1, "url": f"{SITE_URL}/catalogue/dslug/saison1/VOSTFR/", "lang": "vostfr", "_parsed": parsed_s,
    }]
    sonde_saisons = [{
        "saison": 1, "url": f"{SITE_URL}/catalogue/dslug/saison1/vostfr", "lang": "vostfr", "_parsed": parsed_s,
    }]

    async def _http_get(u, cookies):
        return _Resp()

    async def _sonde(*a, **k):
        return sonde_saisons

    monkeypatch.setattr(ep_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    monkeypatch.setattr(ep_mod, "_lister_saisons_par_sondage", _sonde)
    monkeypatch.setattr(ep_mod._ep_disk, "get", lambda k: None)
    monkeypatch.setattr(ep_mod._ep_disk, "set_many", lambda items: None)
    monkeypatch.setattr(parser_mod, "parse_panneaux", lambda text: [])
    monkeypatch.setattr(parser_mod, "parse_saisons", lambda text: fiche_saisons)

    out = asyncio.run(ep_mod.get_episodes_async(fiche))

    assert out["total"] == 1
