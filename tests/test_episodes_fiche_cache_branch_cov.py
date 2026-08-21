"""Regression: the direct-season fallback (fiche has no parseable seasons, URL is
/saisonN/) cached the single-season result under BOTH cache_key and
fiche_cache_key. A later get_episodes_async(fiche_url) would then serve that
incomplete one-season list. The fallback now writes only cache_key.

Order-safe: the in-memory episode cache is snapshotted and restored.
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


def test_saison_fallback_does_not_poison_fiche_cache(monkeypatch, _restore_ep_cache):
    cache = _restore_ep_cache
    url = f"{SITE_URL}/catalogue/zzz-fallback-slug/saison1/vostfr"
    cache_key = url
    fiche_key = f"{SITE_URL}/catalogue/zzz-fallback-slug"

    async def _http_get(u, cookies):
        return _Resp()

    async def _fetch_saison(ck, cookies):
        return {"titre": "T", "episodes": [{"num": 1}], "langues": ["vostfr"], "total": 1}

    async def _sonde(*a, **k):
        return []

    monkeypatch.setattr(ep_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    monkeypatch.setattr(ep_mod, "_fetch_saison", _fetch_saison)
    monkeypatch.setattr(ep_mod, "_lister_saisons_par_sondage", _sonde)
    monkeypatch.setattr(ep_mod._ep_disk, "get", lambda k: None)
    monkeypatch.setattr(parser_mod, "parse_panneaux", lambda text: [])
    monkeypatch.setattr(parser_mod, "parse_saisons", lambda text: [])

    result = asyncio.run(ep_mod.get_episodes_async(url))

    assert result["episodes"] == [{"num": 1}]
    assert cache.get_ep(cache_key) == result
    assert cache.get_ep(fiche_key) is None
