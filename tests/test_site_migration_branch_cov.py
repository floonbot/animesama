"""Migration animes-sama.fr -> anime-sama.to.

Prouve, via les vraies fonctions du projet, que le nouveau site est géré :
- fichier `episodes.js` séparé (format guillemets simples + virgule finale) ;
- recherche en POST `fetch.php` (body `query=`) rendant un fragment
  `.asn-search-result` ;
- langues étendues (var/vf1/vf2) ;
- module `site/` centralisé et configurable par variable d'environnement.

Ordre-safe : le cache saison et les cookies auth sont restaurés, le module
`site` est rechargé à sa valeur par défaut après le test d'override.
"""

import asyncio
import importlib

import pytest

import engine.scraping.episodes as ep_mod
import engine.scraping.http_client as hc
import engine.scraping.players as players_mod
import engine.scraping.search as search_mod
import engine.scraping.site.animessama as site
from engine.auth.manager import auth_manager
from engine.scraping.episodes import _detecter_langue
from engine.scraping.parser import (
    detecter_type_contenu,
    parse_favoris_api,
    parse_panneaux,
)
from engine.scraping.parser._base import _extraire_eps_arrays
from engine.scraping.parser.episodes import parse_episodes


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    players_mod.clear_season_cache()
    saved_cookies = auth_manager.cookies
    monkeypatch.setattr(auth_manager, "cookies", [])
    yield
    auth_manager.cookies = saved_cookies
    players_mod.clear_season_cache()


# --- module site centralisé ----------------------------------------------

def test_site_defaults_and_derivation():
    assert site.SITE_URL == "https://anime-sama.to"
    assert site.SITE_DOMAIN == "anime-sama.to"
    assert site.SEARCH_URL == "https://anime-sama.to/template-php/defaut/fetch.php"
    assert site.SEARCH_URL.startswith(site.SITE_URL)
    assert site.LOGIN_URL.startswith(site.SITE_URL)


def test_site_url_env_override_and_restore(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://animes-sama.fr")
    monkeypatch.delenv("SITE_DOMAIN", raising=False)
    try:
        importlib.reload(site)
        assert site.SITE_URL == "https://animes-sama.fr"
        assert site.SITE_DOMAIN == "animes-sama.fr"
        assert site.SEARCH_URL == "https://animes-sama.fr/template-php/defaut/fetch.php"
    finally:
        monkeypatch.undo()
        importlib.reload(site)
    assert site.SITE_URL == "https://anime-sama.to"


# --- episodes.js (nouveau chemin download) --------------------------------

def test_extraire_eps_arrays_single_quote_trailing_comma():
    eps_js = (
        "var eps1 = [\n'https://vidmoly.to/embed-a.html',\n"
        "'https://video.sibnet.ru/shell.php?videoid=2',\n];\n"
        "var eps2 = [\n'https://sendvid.com/embed/z',\n];"
    )
    assert _extraire_eps_arrays(eps_js) == {
        "eps1": [
            "https://vidmoly.to/embed-a.html",
            "https://video.sibnet.ru/shell.php?videoid=2",
        ],
        "eps2": ["https://sendvid.com/embed/z"],
    }


def test_get_lecteurs_async_reads_episodes_js(monkeypatch):
    eps_js = "var eps1 = [\n'https://vidmoly.to/embed-a.html',\n'https://video.sibnet.ru/v/2',\n];"
    seen = []

    async def fake(url, cookies):
        seen.append(url)
        if url.endswith("/episodes.js"):
            return _Resp(eps_js)
        return _Resp("<html>selectEpisodes vide, aucun eps inline</html>")

    monkeypatch.setattr(players_mod, "http_get", fake)
    res = asyncio.run(players_mod.get_lecteurs_async("/catalogue/re-zero/saison1/vostfr?ep=1"))

    # La page saison est le premier hop (elle porte le filever) ; sans tableau
    # inline, episodes.js reste la source des lecteurs.
    assert seen[0].endswith("/catalogue/re-zero/saison1/vostfr")
    assert seen[1].endswith("/catalogue/re-zero/saison1/vostfr/episodes.js")
    assert res == [{"host": "vidmoly.to", "src": "https://vidmoly.to/embed-a.html"}]


def test_get_lecteurs_async_page_inline_evite_episodes_js(monkeypatch):
    """Page avec tableaux inline et sans filever : elle fait autorité et
    episodes.js n'est pas demandé — une requête économisée."""
    seen = []

    async def fake(url, cookies):
        seen.append(url)
        if url.endswith("/episodes.js"):
            return _Resp("/* fichier absent / sans tableau */")
        return _Resp('var eps1=["https://a.tld/1","https://b.tld/2"]')

    monkeypatch.setattr(players_mod, "http_get", fake)
    res = asyncio.run(players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=2"))

    assert seen == [site.SITE_URL + "/catalogue/x/saison1/vostfr"]
    assert res == [{"host": "b.tld", "src": "https://b.tld/2"}]


# --- recherche POST fetch.php --------------------------------------------

_SEARCH_FRAGMENT = (
    '<a href="https://anime-sama.to/catalogue/re-zero/" class="asn-search-result">'
    '  <img class="asn-search-result-img" src="https://raw.githubusercontent.com/Anime-Sama/IMG/img/contenu/re-zero.jpg"/>'
    '  <div class="asn-search-result-content">'
    '    <h3 class="asn-search-result-title">Re:Zero</h3>'
    '    <p class="asn-search-result-subtitle">Re:Zero kara Hajimeru Isekai Seikatsu</p>'
    '  </div>'
    '</a>'
)


def test_search_async_posts_query_and_parses_fragment(monkeypatch):
    captured = {}

    async def fake_post(url, cookies, data):
        captured["url"] = url
        captured["data"] = dict(data)
        return _Resp(_SEARCH_FRAGMENT)

    monkeypatch.setattr(search_mod, "http_post", fake_post)
    res = asyncio.run(search_mod.search_async("re zero"))

    assert captured["url"] == search_mod.SEARCH_URL
    assert captured["data"] == {"query": "re zero"}
    assert res and res[0]["nom"] == "Re:Zero"
    assert res[0]["url"] == "https://anime-sama.to/catalogue/re-zero/"


def test_http_post_sends_form_body_and_xrw_header():
    captured = {}

    class _FakeResp:
        ok = True
        status_code = 200
        headers: dict = {}
        encoding = None
        _content = b""
        _content_consumed = False

        def iter_content(self, _n):
            yield b'<a class="asn-search-result" href="/catalogue/x/"></a>'

        def close(self):
            pass

        @property
        def text(self):
            return self._content.decode(self.encoding or "utf-8")

    class _FakeSession:
        def post(self, url, **kwargs):
            captured["url"] = url
            captured["data"] = kwargs.get("data")
            captured["headers"] = kwargs.get("headers")
            return _FakeResp()

    out = hc._http_post(_FakeSession(), search_mod.SEARCH_URL, {"query": "x"})
    assert out is not None
    assert "asn-search-result" in out.text
    assert captured["data"] == {"query": "x"}
    assert captured["headers"].get("X-Requested-With") == "XMLHttpRequest"


# --- langues étendues -----------------------------------------------------

@pytest.mark.parametrize(
    "token,expected",
    [("var", "VAR"), ("vf1", "VF1"), ("vf2", "VF2"), ("va", "VA")],
)
def test_new_language_tokens_recognised(token, expected):
    url = f"https://anime-sama.to/catalogue/x/saison1/{token}"
    result = parse_episodes('var eps1=["u1","u2"]', url)
    assert result["langues"] == [expected]
    assert _detecter_langue(url) == token


# --- favoris via get-data.php (tableaux parallèles) -----------------------

def test_parse_favoris_api_parallel_arrays():
    data = {
        "logged_in": True,
        "favorites": {
            "nom": ["Re:Zero", "Tensei Slime"],
            "url": [
                "https://anime-sama.to/catalogue/re-zero/",
                "/catalogue/tensei-shitara-slime-datta-ken",
            ],
            "img": ["https://cdn.example/re-zero.jpg", ""],
        },
    }
    res = parse_favoris_api(data)
    assert len(res) == 2
    assert res[0] == {
        "nom": "Re:Zero",
        "url": "https://anime-sama.to/catalogue/re-zero/",
        "image": "https://cdn.example/re-zero.jpg",
        "statut": "",
        "type": "anime",
        "listes": ["favoris"],
    }
    assert res[1]["url"] == "https://anime-sama.to/catalogue/tensei-shitara-slime-datta-ken"
    assert res[1]["image"].endswith("/tensei-shitara-slime-datta-ken.jpg")


# --- saisons via panneauAnime + multi-langues ----------------------------

def test_parse_panneaux_reads_seasons_skips_template_and_dedups():
    html = (
        '<script>'
        'panneauAnime("nom", "url");'
        'panneauAnime("Saison 1", "saison1/vostfr");'
        'panneauAnime("Saison 2 Partie 1", "saison2-1/vostfr");'
        'panneauAnime("Film", "film/vostfr");'
        'panneauAnime("Doublon", "saison1/vf");'
        '</script>'
    )
    assert parse_panneaux(html) == [
        {"nom": "Saison 1", "seg": "saison1", "lang": "vostfr"},
        {"nom": "Saison 2 Partie 1", "seg": "saison2-1", "lang": "vostfr"},
        {"nom": "Film", "seg": "film", "lang": "vostfr"},
    ]
    assert parse_panneaux("") == []


def test_extraire_eps_arrays_ignores_js_line_comment_slots():
    js = (
        "var eps1 = [\n"
        "'https://a.tld/1',\n"
        "'https://a.tld/2',\n"
        "//'https://a.tld/placeholder-non-encore-sorti'\n"
        "];"
    )
    assert _extraire_eps_arrays(js) == {"eps1": ["https://a.tld/1", "https://a.tld/2"]}


def test_episodes_depuis_panneaux_multilang_and_labels(monkeypatch):
    async def fake_arrays(url, cookies):
        if url.endswith("/saison1/vostfr"):
            return {"eps1": ["https://h/1", "https://h/2", "https://h/3"]}, True
        if url.endswith("/saison1/vf"):
            return {"eps1": ["https://h/1", "https://h/2"]}, True
        if url.endswith("/saison2-1/vostfr"):
            return {"eps1": ["https://h/x"]}, True
        return {}, False

    monkeypatch.setattr(ep_mod, "_fetch_saison_arrays", fake_arrays)
    panneaux = [
        {"nom": "Saison 1", "seg": "saison1", "lang": "vostfr"},
        {"nom": "Saison 2 Partie 1", "seg": "saison2-1", "lang": "vostfr"},
    ]
    result, complet = asyncio.run(
        ep_mod._episodes_depuis_panneaux("slug", "<h1>Mon Anime</h1>", panneaux, [])
    )
    assert complet is True
    assert result["titre"] == "Mon Anime"
    assert result["langues"] == ["VF", "VOSTFR"]
    assert result["total"] == 6

    s1_vostfr = [e for e in result["episodes"] if e["saison"] == 1 and e["langue"] == "VOSTFR"]
    assert len(s1_vostfr) == 3
    assert s1_vostfr[0]["saison_nom"] == "Saison 1"
    assert s1_vostfr[0]["url"] == "https://anime-sama.to/catalogue/slug/saison1/vostfr?ep=1"

    s2 = [e for e in result["episodes"] if e["saison"] == 2]
    assert len(s2) == 1
    assert s2[0]["saison_nom"] == "Saison 2 Partie 1"
    assert s2[0]["langue"] == "VOSTFR"
    assert s2[0]["url"] == "https://anime-sama.to/catalogue/slug/saison2-1/vostfr?ep=1"


def test_parse_panneaux_prefixes_secondary_sections():
    html = (
        '<h2>Serie</h2><div><script>'
        'panneauAnime("Saison 1","saison1/vostfr");'
        'panneauAnime("OAV","oav/vostfr");'
        '</script></div>'
        '<h2>The Anime</h2><div><script>'
        'panneauAnime("Saison 1","saison1hs/vostfr");'
        '</script></div>'
    )
    assert parse_panneaux(html) == [
        {"nom": "Saison 1", "seg": "saison1", "lang": "vostfr"},
        {"nom": "OAV", "seg": "oav", "lang": "vostfr"},
        {"nom": "The Anime - Saison 1", "seg": "saison1hs", "lang": "vostfr"},
    ]


def test_dossier_saison_and_nom_fichier_use_saison_nom():
    from engine.scraping.parser import dossier_saison, nom_fichier

    assert dossier_saison("Saison 1") == "Saison 01"
    assert dossier_saison("OAV") == "OAV"
    assert dossier_saison("The Anime - Saison 1") == "The Anime - Saison 1"
    assert dossier_saison("", 3) == "Saison 03"

    assert nom_fichier("Rick", 1, 5, "VOSTFR", "Saison 1") == "Rick - S01E005 VOSTFR"
    assert nom_fichier("Rick", 10, 1, "VOSTFR", "OAV") == "Rick - OAV - E001 VOSTFR"
    assert nom_fichier("Rick", 11, 2, "", "The Anime - Saison 1") == "Rick - The Anime - Saison 1 - E002"
    assert nom_fichier("Rick", 2, 3, "VF") == "Rick - S02E003 VF"


def test_construire_episodes_fusionne_saisons_mono_episode():
    infos = [
        (1, "Saison 1", "saison1", "vostfr", [1]),
        (2, "Saison 2", "saison2", "vostfr", [1]),
        (3, "Saison 3", "saison3", "vostfr", [1]),
    ]
    eps = ep_mod._construire_episodes("slug", "T", infos)
    assert [(e["saison"], e["episode"]) for e in eps] == [(1, 1), (1, 2), (1, 3)]
    assert all(e["saison_nom"] == "Saison 1" for e in eps)
    assert eps[1]["url"] == "https://anime-sama.to/catalogue/slug/saison2/vostfr?ep=1"


def test_construire_episodes_no_fusion_multi_ep_or_non_numeric():
    infos = [
        (1, "Saison 1", "saison1", "vostfr", list(range(1, 13))),
        (2, "Saison 2", "saison2", "vostfr", [1]),
    ]
    eps = ep_mod._construire_episodes("slug", "T", infos)
    assert sorted({e["saison"] for e in eps}) == [1, 2]
    assert len([e for e in eps if e["saison"] == 1]) == 12

    infos2 = [
        (1, "S1", "saison1", "vostfr", [1]),
        (2, "S2 Partie 1", "saison2-1", "vostfr", [1]),
    ]
    eps2 = ep_mod._construire_episodes("slug", "T", infos2)
    assert sorted({e["saison"] for e in eps2}) == [1, 2]


def test_episodes_reels_skips_placeholder_urls():
    from engine.scraping.parser._base import _est_url_placeholder

    assert _est_url_placeholder("https://video.sibnet.ru/shell.php?videoid=") is True
    assert _est_url_placeholder("https://vidmoly.to/embed-.html") is True
    assert _est_url_placeholder("https://sendvid.com/embed/") is True
    assert _est_url_placeholder("https://vk.com/video_ext.php?oid=&hd=3") is True
    assert _est_url_placeholder("") is True
    assert _est_url_placeholder("https://vk.com/video_ext.php?oid=-12&id=34&hd=3") is False
    assert _est_url_placeholder("https://video.sibnet.ru/shell.php?videoid=6235096") is False
    assert _est_url_placeholder("https://vidmoly.to/embed-3ic4o60.html") is False

    assert ep_mod._episodes_reels({"eps1": ["https://a/1"], "eps2": ["https://b/1"]}) == [1]
    assert ep_mod._episodes_reels(
        {"eps1": ["https://video.sibnet.ru/shell.php?videoid="], "eps2": ["https://vidmoly.to/embed-.html"]}
    ) == []
    assert ep_mod._episodes_reels(
        {"eps1": ["https://a/1", "https://a/2", "https://a/x?videoid="]}
    ) == [1, 2]


def test_detecter_type_contenu_reads_panneau_calls():
    both = '<script>panneauAnime("Saison 1", "saison1/vostfr"); panneauScan("Scans", "scan/vf");</script>'
    assert detecter_type_contenu(both) == {"has_anime": True, "has_scan": True}
    assert detecter_type_contenu('<script>panneauAnime("S1","saison1/vostfr")</script>') == {
        "has_anime": True, "has_scan": False,
    }
    assert detecter_type_contenu('<script>panneauScan("Scans","scan/vf")</script>') == {
        "has_anime": False, "has_scan": True,
    }
    assert detecter_type_contenu('<a href="/catalogue/x/saison1">a</a>') == {
        "has_anime": True, "has_scan": False,
    }


def test_parse_favoris_api_empty_and_malformed():
    assert parse_favoris_api({"logged_in": True}) == []
    assert parse_favoris_api(
        {"logged_in": True, "favorites": {"nom": [], "url": [], "img": []}}
    ) == []
    assert parse_favoris_api({}) == []
    assert parse_favoris_api(None) == []
    assert parse_favoris_api(
        {"favorites": {"url": ["https://evil.com/x"], "nom": ["x"], "img": [""]}}
    ) == []
