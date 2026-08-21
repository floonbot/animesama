"""Catalogue filtré (nouveau site) : GET /catalogue?type[]/genre[]/langue[]/current[]&page
rend des cartes server-rendered `.catalog-card` — parsées par parse_search_results.
"""

import asyncio

import engine.auth.manager as auth_mod
import engine.scraping.catalogue as cat_mod
from engine.scraping.catalogue import _construire_url, _extraire_genres
from engine.scraping.site.animessama import SITE_URL


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text


def _fake_auth(monkeypatch, cookies=None):
    class _AM:
        pass

    am = _AM()
    am.cookies = cookies if cookies is not None else []
    monkeypatch.setattr(auth_mod, "auth_manager", am)


def test_construire_url_omits_empty_and_page1():
    assert _construire_url("", "", "", "", 1) == f"{SITE_URL}/catalogue"
    u = _construire_url("Action", "Film", "VF", "En cours", 3)
    assert u.startswith(f"{SITE_URL}/catalogue?")
    assert "genre%5B%5D=Action" in u
    assert "type%5B%5D=Film" in u
    assert "langue%5B%5D=VF" in u
    assert "current%5B%5D=En+cours" in u
    assert "page=3" in u
    assert "page=" not in _construire_url("Action", "", "", "", 1)


def test_extraire_genres_dedups_and_empty():
    html = (
        '<input name="genre[]" value="Action">'
        '<input name="genre[]" value="Aventure">'
        '<input name="genre[]" value="Action">'
        '<input name="genre[]" value="">'
    )
    assert _extraire_genres(html) == ["Action", "Aventure"]
    assert _extraire_genres("") == []


def test_catalogue_async_builds_url_and_parses(monkeypatch):
    _fake_auth(monkeypatch, cookies=[{"name": "c", "value": "v"}])
    seen = {}

    async def fake_get(url, cookies):
        seen["url"] = url
        seen["cookies"] = cookies
        return _Resp(
            '<a href="https://anime-sama.to/catalogue/naruto/" class="asn-search-result">'
            '<h3 class="asn-search-result-title">Naruto</h3></a>'
        )

    monkeypatch.setattr(cat_mod, "http_get", fake_get)
    res = asyncio.run(cat_mod.catalogue_async(genre="Action", type_="Anime", page=2))

    assert "genre%5B%5D=Action" in seen["url"]
    assert "type%5B%5D=Anime" in seen["url"]
    assert "page=2" in seen["url"]
    assert seen["cookies"] == [{"name": "c", "value": "v"}]
    assert res and res[0]["nom"] == "Naruto"
    assert res[0]["url"] == "https://anime-sama.to/catalogue/naruto/"


def test_catalogue_async_bad_page_defaults_to_one(monkeypatch):
    _fake_auth(monkeypatch)
    seen = {}

    async def fake_get(url, cookies):
        seen["url"] = url
        return _Resp("")

    monkeypatch.setattr(cat_mod, "http_get", fake_get)
    asyncio.run(cat_mod.catalogue_async(page="oops"))
    assert "page=" not in seen["url"]


def test_catalogue_async_no_response_returns_empty(monkeypatch):
    _fake_auth(monkeypatch)

    async def fake_get(url, cookies):
        return None

    monkeypatch.setattr(cat_mod, "http_get", fake_get)
    assert asyncio.run(cat_mod.catalogue_async(genre="Action")) == []


def test_catalogue_async_exception_returns_empty(monkeypatch):
    _fake_auth(monkeypatch)

    async def fake_get(url, cookies):
        raise RuntimeError("network down")

    monkeypatch.setattr(cat_mod, "http_get", fake_get)
    assert asyncio.run(cat_mod.catalogue_async()) == []


def test_catalogue_genres_async(monkeypatch):
    _fake_auth(monkeypatch)

    async def fake_get(url, cookies):
        assert url == cat_mod.CATALOGUE_URL
        return _Resp('<input name="genre[]" value="Action"><input name="genre[]" value="Drame">')

    monkeypatch.setattr(cat_mod, "http_get", fake_get)
    assert asyncio.run(cat_mod.catalogue_genres_async()) == ["Action", "Drame"]


def test_catalogue_genres_async_no_response(monkeypatch):
    _fake_auth(monkeypatch)

    async def fake_get(url, cookies):
        return None

    monkeypatch.setattr(cat_mod, "http_get", fake_get)
    assert asyncio.run(cat_mod.catalogue_genres_async()) == []
