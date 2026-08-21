"""Deterministic tests for the remaining small-parser gaps.

Covers the branches of engine/scraping/players.get_lecteurs_async (ep query
defaulting, http_get None, exception swallowing, the leading-'/' SITE_URL
prefix and the unsafe-url gate) plus the parser-level edge cases of
parser/players.parse_lecteurs, parser/profile.parse_favoris_api and
parser/search.parse_search_results not exercised by
tests/test_players_parsing.py.

All HTML/JS fixtures are inline strings parsed with the real deterministic
BeautifulSoup; the single async surface monkeypatches the module-level
http_get and auth_manager.cookies (the real _is_safe_url gate is left
unmocked and genuinely exercised) so no network, subprocess, browser, thread
work or wall-clock is involved. The shared auth_manager singleton's cookies
attribute is snapshotted and restored by an autouse fixture so the tests stay
order-independent.
"""

import asyncio

import pytest

import engine.scraping.players as players_mod
from engine.auth.manager import auth_manager
from engine.scraping.parser.players import parse_lecteurs
from engine.scraping.parser.profile import parse_favoris_api
from engine.scraping.parser.search import parse_search_results
from engine.scraping.site.animessama import COVERS_BASE, SITE_URL


@pytest.fixture(autouse=True)
def _restore_auth_cookies():
    players_mod.clear_season_cache()
    saved = auth_manager.cookies
    yield
    auth_manager.cookies = saved
    players_mod.clear_season_cache()


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


def _install_get(monkeypatch, fake, *, cookies=None):
    monkeypatch.setattr(players_mod, "http_get", fake)
    monkeypatch.setattr(auth_manager, "cookies", cookies if cookies is not None else [])


def test_get_lecteurs_async_invalid_ep_defaults_to_one(monkeypatch):
    """A non-integer ?ep value falls back to ep 1 (index 0)."""
    recorded = {}

    async def fake_http_get(url, cookies):
        recorded["url"] = url
        return _FakeResp('var eps1=["https://a.tld/1","https://b.tld/2"]')

    _install_get(monkeypatch, fake_http_get)

    result = asyncio.run(
        players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=abc")
    )

    assert recorded["url"] == SITE_URL + "/catalogue/x/saison1/vostfr"
    assert result == [{"host": "a.tld", "src": "https://a.tld/1"}]


def test_get_lecteurs_async_missing_ep_defaults_to_one(monkeypatch):
    """A URL with no ?ep parameter resolves to ep 1 (index 0)."""

    async def fake_http_get(url, cookies):
        return _FakeResp('var eps1=["https://a.tld/1","https://b.tld/2"]')

    _install_get(monkeypatch, fake_http_get)

    result = asyncio.run(
        players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr")
    )

    assert result == [{"host": "a.tld", "src": "https://a.tld/1"}]


def _spy_delegate(monkeypatch, sink):
    """Replace the players-parser delegate lecteurs_depuis_arrays (resolved at
    call time inside get_lecteurs_async) with a spy recording the ep_num it
    actually receives, so the async-layer coercion is pinned independently of
    the delegate's own internal re-coercion."""
    import engine.scraping.parser.players as players_parser

    def _spy(eps_arrays, ep_num):
        sink["ep_num"] = ep_num
        return [{"host": "a.tld", "src": "https://a.tld/1"}]

    monkeypatch.setattr(players_parser, "lecteurs_depuis_arrays", _spy)


def test_get_lecteurs_async_zero_ep_coerced_to_one(monkeypatch):
    """ep=0 is coerced up to 1 by get_lecteurs_async BEFORE delegating."""
    sink = {}
    _spy_delegate(monkeypatch, sink)

    async def fake_http_get(url, cookies):
        return _FakeResp("<html></html>")

    _install_get(monkeypatch, fake_http_get)

    result = asyncio.run(
        players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=0")
    )

    assert sink["ep_num"] == 1
    assert result == [{"host": "a.tld", "src": "https://a.tld/1"}]


def test_get_lecteurs_async_negative_ep_coerced_to_one(monkeypatch):
    """A negative ?ep is coerced up to 1 at the async layer before the delegate runs."""
    sink = {}
    _spy_delegate(monkeypatch, sink)

    async def fake_http_get(url, cookies):
        return _FakeResp("<html></html>")

    _install_get(monkeypatch, fake_http_get)

    result = asyncio.run(
        players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=-5")
    )

    assert sink["ep_num"] == 1
    assert result == [{"host": "a.tld", "src": "https://a.tld/1"}]


def test_get_lecteurs_async_http_get_none_returns_empty(monkeypatch):
    """A falsy http_get response yields an empty lecteur list."""
    seen = {"called": False}

    async def fake_http_get(url, cookies):
        seen["called"] = True
        return None

    _install_get(monkeypatch, fake_http_get)

    result = asyncio.run(
        players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1")
    )

    assert result == []
    assert seen["called"] is True


def test_get_lecteurs_async_http_get_exception_returns_empty(monkeypatch):
    """An exception raised during fetch is swallowed and returns empty."""

    async def fake_http_get(url, cookies):
        raise RuntimeError("network down")

    _install_get(monkeypatch, fake_http_get)

    result = asyncio.run(
        players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=1")
    )

    assert result == []


def test_get_lecteurs_async_empty_url_rejected_without_fetch(monkeypatch):
    """An empty URL fails the safety gate before http_get runs."""
    seen = {"called": False}

    async def fake_http_get(url, cookies):
        seen["called"] = True
        return _FakeResp("")

    _install_get(monkeypatch, fake_http_get)

    result = asyncio.run(players_mod.get_lecteurs_async(""))

    assert result == []
    assert seen["called"] is False


def test_get_lecteurs_async_passes_cookies_and_strips_query(monkeypatch):
    """The auth cookies are forwarded and the query string is stripped."""
    recorded = {}

    async def fake_http_get(url, cookies):
        recorded["url"] = url
        recorded["cookies"] = cookies
        return _FakeResp('var eps1=["https://a.tld/1"]')

    cookies = [{"name": "sess", "value": "tok"}]
    _install_get(monkeypatch, fake_http_get, cookies=cookies)

    result = asyncio.run(
        players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr/?ep=1")
    )

    assert recorded["url"] == SITE_URL + "/catalogue/x/saison1/vostfr"
    assert recorded["cookies"] == cookies
    assert result == [{"host": "a.tld", "src": "https://a.tld/1"}]


def test_parse_lecteurs_no_arrays_returns_empty():
    """HTML without any eps array declaration yields an empty list."""
    assert parse_lecteurs("<html><body>no arrays</body></html>", 1) == []


def test_parse_lecteurs_non_int_ep_num_coerced_to_one():
    """A non-integer ep_num is coerced to 1 (index 0)."""
    html = 'var eps1=["https://a.tld/1","https://b.tld/2"]'
    assert parse_lecteurs(html, "oops") == [
        {"host": "a.tld", "src": "https://a.tld/1"}
    ]


def test_parse_lecteurs_negative_ep_num_coerced_to_one():
    """A negative ep_num is coerced up to 1 (index 0)."""
    html = 'var eps1=["https://a.tld/1","https://b.tld/2"]'
    assert parse_lecteurs(html, -4) == [
        {"host": "a.tld", "src": "https://a.tld/1"}
    ]


def test_parse_lecteurs_malformed_host_falls_back_to_inconnu():
    """An http src whose hostname parse raises yields host 'Inconnu'."""
    html = 'var eps1=["http://[bad"]'
    assert parse_lecteurs(html, 1) == [{"host": "Inconnu", "src": "http://[bad"}]


def test_parse_lecteurs_empty_slot_is_a_hole_not_a_shift():
    """An empty slot is a per-episode hole: ep1 (the empty) yields nothing, and
    ep2 keeps its own url. Dropping the empty would wrongly serve ep2 as ep1."""
    html = 'var eps1=["","https://ok.tld/v"]'
    assert parse_lecteurs(html, 1) == []
    assert parse_lecteurs(html, 2) == [{"host": "ok.tld", "src": "https://ok.tld/v"}]


def test_parse_favoris_api_donnees_vides_rendent_une_liste_vide():
    """Un bloc absent ou non conforme court-circuite vers une liste vide."""
    assert parse_favoris_api({}) == []
    assert parse_favoris_api({"favorites": "notadict"}) == []
    assert parse_favoris_api({"favorites": {"url": "notalist"}}) == []


def test_parse_favoris_api_skips_non_str_and_empty_url_items():
    """Les entrees non-str et les url vides sont ignorees, pas le lot entier."""
    data = {"favorites": {
        "url": [42, "", "/catalogue/kept"],
        "nom": ["", "", "Kept"],
    }}
    assert parse_favoris_api(data) == [
        {
            "nom": "Kept",
            "url": SITE_URL + "/catalogue/kept",
            "image": f"{COVERS_BASE}/kept.jpg",
            "statut": "",
            "type": "anime",
            "listes": ["favoris"],
        }
    ]


def test_parse_favoris_api_keeps_absolute_onsite_url_and_explicit_image():
    """Une url deja absolue et interne garde son image propre."""
    data = {"favorites": {
        "url": [SITE_URL + "/catalogue/onsite"],
        "nom": ["On"],
        "img": ["https://cdn/p.png"],
    }}
    assert parse_favoris_api(data) == [
        {
            "nom": "On",
            "url": SITE_URL + "/catalogue/onsite",
            "image": "https://cdn/p.png",
            "statut": "",
            "type": "anime",
            "listes": ["favoris"],
        }
    ]


def test_parse_favoris_api_drops_absolute_offsite_url():
    """Une url absolue hors-site est ecartee par le controle d'origine."""
    data = {"favorites": {"url": ["http://other.example/catalogue/x"], "nom": ["Off"]}}
    assert parse_favoris_api(data) == []


def test_parse_search_results_empty_html_returns_empty():
    """Empty HTML yields no search results."""
    assert parse_search_results("") == []


def test_parse_search_results_name_from_img_alt_when_no_heading():
    """With no heading text the image alt supplies the nom."""
    html = '<a href="/catalogue/naruto"><img alt="Naruto Alt"></a>'
    assert parse_search_results(html)[0]["nom"] == "Naruto Alt"


def test_parse_search_results_strips_parenthesized_lang_suffix():
    """A '(VOSTFR)' suffix on the heading is stripped from the nom."""
    html = '<a href="/catalogue/naruto"><h2>Naruto (VOSTFR)</h2></a>'
    assert parse_search_results(html)[0]["nom"] == "Naruto"


def test_parse_search_results_prefers_img_src_over_fallbacks():
    """A plain img src wins over data-src / data-lazy-src and the cover URL."""
    html = (
        '<a href="/catalogue/naruto"><h2>Naruto</h2>'
        '<img src="https://cdn/s.jpg" data-src="https://cdn/d.jpg"></a>'
    )
    assert parse_search_results(html)[0]["image"] == "https://cdn/s.jpg"


def test_parse_search_results_image_from_data_lazy_src():
    """data-lazy-src is used when src and data-src are absent."""
    html = (
        '<a href="/catalogue/naruto"><h2>Naruto</h2>'
        '<img data-lazy-src="https://cdn/l.jpg"></a>'
    )
    assert parse_search_results(html)[0]["image"] == "https://cdn/l.jpg"


def test_parse_search_results_keeps_absolute_href():
    """An absolute href is used verbatim as the result url."""
    html = '<a href="https://anime-sama.to/catalogue/naruto"><h2>Naruto</h2></a>'
    assert parse_search_results(html)[0]["url"] == (
        "https://anime-sama.to/catalogue/naruto"
    )


def test_parse_search_results_dedupes_repeated_href_in_seen():
    """A repeated identical href is collapsed by the seen-set guard."""
    html = (
        '<a href="/catalogue/naruto"><h2>First</h2></a>'
        '<a href="/catalogue/naruto"><h2>Second</h2></a>'
    )
    results = parse_search_results(html)
    assert len(results) == 1
    assert results[0]["nom"] == "First"
