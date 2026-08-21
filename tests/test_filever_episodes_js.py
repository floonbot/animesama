"""Bug 0 — le paramètre anti-cache `filever` était omis.

Le HTML d'une page saison porte `<script src='episodes.js?filever=1293'>`. Le
navigateur charge cette URL versionnée ; l'app fetchait `/episodes.js` nu et
récupérait une copie de cache d'où l'épisode le plus récent est absent.

Vérifié le 2026-08-05 sur trapped-in-a-dating-sim-.../saison2/vostfr :
/episodes.js → 1059 o (4 épisodes), /episodes.js?filever=1293 → 1293 o (5).

Double conséquence : check-updates ne voyait pas le nouvel épisode, et
get_lecteurs_async("...?ep=5") renvoyait 0 lecteur.

Le serveur factice ci-dessous sert deux contenus selon la présence de filever.
"""

import asyncio

import pytest

import engine.scraping.episodes as episodes_mod
import engine.scraping.players as players_mod
from engine.auth.manager import auth_manager
from engine.scraping.site.animessama import SITE_URL

SAISON = "/catalogue/dating-sim/saison2/vostfr"

_EPS_PERIMEE = (
    'var eps1 = ["https://a.tld/1","https://b.tld/2","https://c.tld/3","https://d.tld/4"];'
)
_EPS_FRAICHE = (
    'var eps1 = ["https://a.tld/1","https://b.tld/2","https://c.tld/3",'
    '"https://d.tld/4","https://e.tld/5"];'
)

_HTML_FILEVER = (
    "<html><head></head><body><h1>Saison 2</h1>"
    "<script src='episodes.js?filever=1293'></script></body></html>"
)
_HTML_SANS_FILEVER = "<html><head></head><body><h1>Saison 2</h1></body></html>"
_HTML_ARRAYS_INLINE = f"<html><body><script>{_EPS_FRAICHE}</script></body></html>"


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status_code = 200


def _origine(html: str, seen: list | None = None, html_ko: bool = False):
    """Sert episodes.js périmé sans filever, frais avec."""

    async def fake_http_get(url, cookies):
        if seen is not None:
            seen.append(url)
        if "/episodes.js?filever=" in url:
            return _FakeResp(_EPS_FRAICHE)
        if url.endswith("/episodes.js"):
            return _FakeResp(_EPS_PERIMEE)
        if html_ko:
            return None
        return _FakeResp(html)

    return fake_http_get


@pytest.fixture(autouse=True)
def _isolement(monkeypatch):
    players_mod.clear_season_cache()
    monkeypatch.setattr(auth_manager, "cookies", [])
    yield
    players_mod.clear_season_cache()


def _install(monkeypatch, fake):
    monkeypatch.setattr(players_mod, "http_get", fake)
    monkeypatch.setattr(episodes_mod, "http_get", fake)


# --- l'URL versionnée -----------------------------------------------------

def test_url_episodes_js_reprend_le_filever_du_html():
    url = players_mod.url_episodes_js(SITE_URL + SAISON, _HTML_FILEVER)
    assert url == f"{SITE_URL}{SAISON}/episodes.js?filever=1293"


def test_url_episodes_js_sans_filever_reste_nue():
    url = players_mod.url_episodes_js(SITE_URL + SAISON, _HTML_SANS_FILEVER)
    assert url == f"{SITE_URL}{SAISON}/episodes.js"


def test_url_episodes_js_ignore_la_query_de_la_saison():
    url = players_mod.url_episodes_js(SITE_URL + SAISON + "?ep=5", _HTML_FILEVER)
    assert url == f"{SITE_URL}{SAISON}/episodes.js?filever=1293"


def test_url_episodes_js_refuse_un_filever_non_numerique():
    html = "<script src='episodes.js?filever=abc'></script>"
    url = players_mod.url_episodes_js(SITE_URL + SAISON, html)
    assert url == f"{SITE_URL}{SAISON}/episodes.js"


# --- players.py -----------------------------------------------------------

def test_fetch_saison_arrays_lit_la_version_fraiche(monkeypatch):
    seen: list = []
    _install(monkeypatch, _origine(_HTML_FILEVER, seen))

    arrays, ok = asyncio.run(
        players_mod._fetch_saison_arrays(SITE_URL + SAISON, [])
    )

    assert ok is True
    assert len(arrays["eps1"]) == 5, "l'app doit voir le 5e épisode"
    assert any("filever=1293" in u for u in seen)


def test_dernier_episode_est_telechargeable(monkeypatch):
    """La conséquence utilisateur : ?ep=5 renvoyait 0 lecteur."""
    _install(monkeypatch, _origine(_HTML_FILEVER))

    ep5 = asyncio.run(players_mod.get_lecteurs_async(SAISON + "?ep=5"))

    assert ep5 == [{"host": "e.tld", "src": "https://e.tld/5"}]


def test_sans_filever_on_retombe_sur_l_ancien_chemin(monkeypatch):
    seen: list = []
    _install(monkeypatch, _origine(_HTML_SANS_FILEVER, seen))

    arrays, ok = asyncio.run(
        players_mod._fetch_saison_arrays(SITE_URL + SAISON, [])
    )

    assert ok is True
    assert len(arrays["eps1"]) == 4
    assert seen[-1] == f"{SITE_URL}{SAISON}/episodes.js"
    assert not any("filever" in u for u in seen)


def test_arrays_inline_sans_filever_evitent_une_requete(monkeypatch):
    seen: list = []
    _install(monkeypatch, _origine(_HTML_ARRAYS_INLINE, seen))

    arrays, ok = asyncio.run(
        players_mod._fetch_saison_arrays(SITE_URL + SAISON, [])
    )

    assert ok is True
    assert len(arrays["eps1"]) == 5
    assert len(seen) == 1


def test_page_saison_injoignable_degrade_proprement(monkeypatch):
    _install(monkeypatch, _origine(_HTML_FILEVER, html_ko=True))

    arrays, ok = asyncio.run(
        players_mod._fetch_saison_arrays(SITE_URL + SAISON, [])
    )

    assert ok is False
    assert arrays == {}


# --- episodes.py ----------------------------------------------------------

def test_fetch_saison_parsed_utilise_le_filever(monkeypatch):
    seen: list = []
    _install(monkeypatch, _origine(_HTML_FILEVER, seen))

    parsed = asyncio.run(
        episodes_mod._fetch_saison_parsed(SITE_URL + SAISON, [])
    )

    assert len(parsed.get("episodes") or []) == 5
    assert any("filever=1293" in u for u in seen)


def test_fetch_saison_parsed_sans_filever_reste_fonctionnel(monkeypatch):
    seen: list = []
    _install(monkeypatch, _origine(_HTML_SANS_FILEVER, seen))

    parsed = asyncio.run(
        episodes_mod._fetch_saison_parsed(SITE_URL + SAISON, [])
    )

    assert len(parsed.get("episodes") or []) == 4
    assert not any("filever" in u for u in seen)
