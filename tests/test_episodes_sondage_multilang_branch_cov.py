import asyncio

import pytest

import engine.scraping.episodes as ep
import engine.scraping.parser as parser_mod
from engine.auth.manager import auth_manager
from engine.scraping.site.animessama import SITE_URL


class FakeResp:
    def __init__(self, text):
        self.text = text


class FakeCache:
    def __init__(self):
        self.mem = {}

    def get_ep(self, key):
        return self.mem.get(key)

    def set_ep(self, key, data):
        self.mem[key] = data

    def ep_lock(self, key):
        return asyncio.Lock()


class FakeDisk:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set_many(self, items):
        self.store.update(items)


@pytest.fixture(autouse=True)
def _restore_globals():
    orig = (
        ep._ep_disk, ep.cache, ep.http_get, ep._is_safe_url,
        auth_manager.cookies, parser_mod.parse_saisons, parser_mod.parse_episodes,
    )
    yield
    (
        ep._ep_disk, ep.cache, ep.http_get, ep._is_safe_url,
        auth_manager.cookies, parser_mod.parse_saisons, parser_mod.parse_episodes,
    ) = orig


def test_sondage_ne_perd_pas_les_saisons_dune_autre_langue(monkeypatch):
    monkeypatch.setattr(ep, "_ep_disk", FakeDisk())
    monkeypatch.setattr(ep, "cache", FakeCache())
    monkeypatch.setattr(ep, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(auth_manager, "cookies", [])

    season_pages = {
        f"{SITE_URL}/catalogue/naruto/saison1/vostfr": FakeResp("<s1-vostfr>"),
        f"{SITE_URL}/catalogue/naruto/saison1/vf": FakeResp("<s1-vf>"),
    }

    async def _http_get(url, cookies):
        if url == f"{SITE_URL}/catalogue/naruto":
            return FakeResp("<fiche>")
        return season_pages.get(url)

    monkeypatch.setattr(ep, "http_get", _http_get)

    monkeypatch.setattr(
        parser_mod, "parse_saisons",
        lambda html: [
            {"saison": 1, "url": f"{SITE_URL}/catalogue/naruto/saison1/vostfr", "lang": "vostfr"},
            {"saison": 1, "url": f"{SITE_URL}/catalogue/naruto/saison1/vf", "lang": "vf"},
        ],
    )

    def _parse_episodes(text, url):
        if text == "<s1-vostfr>":
            return {"titre": "Naruto", "episodes": [{"n": 1, "l": "vostfr"}], "langues": ["vostfr"]}
        if text == "<s1-vf>":
            return {"titre": "Naruto", "episodes": [{"n": 1, "l": "vf"}], "langues": ["vf"]}
        return {"titre": "Naruto", "episodes": [], "langues": []}

    monkeypatch.setattr(parser_mod, "parse_episodes", _parse_episodes)
    monkeypatch.setattr(ep.time, "time", lambda: 1000.0)

    out = asyncio.run(ep.get_episodes_async(f"{SITE_URL}/catalogue/naruto"))

    assert "vostfr" in out["langues"]
    assert "vf" in out["langues"]
    assert out["total"] == 2
