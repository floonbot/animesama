"""Deterministic parsing tests for the players/episodes/search/profile zone.

All fixtures are inline HTML/JS strings parsed with the real (deterministic)
BeautifulSoup. The single async test monkeypatches the module-level http_get
symbol so no network or wall-clock time is involved.
"""

import asyncio

import pytest

import engine.scraping.players as players_mod
from engine.scraping.parser._base import (
    MAX_EPS_ARRAYS,
    _extraire_eps_arrays,
    _extraire_tableau_js,
)
from engine.scraping.parser.episodes import parse_episodes, parse_saisons
from engine.scraping.parser.players import parse_lecteurs
from engine.scraping.parser.profile import (
    detecter_type_contenu,
)
from engine.scraping.parser.search import parse_search_results
from engine.scraping.site.animessama import COVERS_BASE, SITE_URL


@pytest.fixture(autouse=True)
def _clear_season_cache():
    players_mod.clear_season_cache()
    yield
    players_mod.clear_season_cache()


def _select_options(n: int) -> str:
    options = "".join(f"<option>E{i}</option>" for i in range(n))
    return f'<select id="selectEpisodes">{options}</select>'


def test_parse_lecteurs_maps_ep1_to_index0_sibnet_host():
    """ep_num 1 maps to index 0 and the sibnet host is extracted."""
    html = (
        'var eps1 = ["https://video.sibnet.ru/shell.php?videoid=1",'
        '"https://vidmoly.to/embed-abc.html"]'
    )
    assert parse_lecteurs(html, 1) == [
        {"host": "video.sibnet.ru", "src": "https://video.sibnet.ru/shell.php?videoid=1"}
    ]


def test_parse_lecteurs_maps_ep2_to_index1_vidmoly_host():
    """ep_num 2 maps to index 1 (idx = ep_num - 1) and host is extracted."""
    html = (
        'var eps1 = ["https://video.sibnet.ru/shell.php?videoid=1",'
        '"https://vidmoly.to/embed-abc.html"]'
    )
    assert parse_lecteurs(html, 2) == [
        {"host": "vidmoly.to", "src": "https://vidmoly.to/embed-abc.html"}
    ]


def test_parse_lecteurs_rejects_protocol_relative_src():
    """A non-http (protocol-relative) src at the requested index is dropped."""
    html = 'var eps1 = ["//cdn.example/x","https://ok.tld/v"]'
    assert parse_lecteurs(html, 1) == []


def test_parse_lecteurs_skips_out_of_range_index():
    """An ep_num beyond the array length yields no lecteur."""
    html = 'var eps1 = ["//cdn.example/x","https://ok.tld/v"]'
    assert parse_lecteurs(html, 99) == []


def test_parse_lecteurs_coerces_zero_ep_to_one():
    """ep_num 0 is coerced to 1, hitting the rejected first entry => empty."""
    html = 'var eps1 = ["//cdn.example/x","https://ok.tld/v"]'
    assert parse_lecteurs(html, 0) == []


def test_parse_lecteurs_keeps_valid_https_entry():
    """The valid https entry at the requested index is returned."""
    html = 'var eps1 = ["//cdn.example/x","https://ok.tld/v"]'
    assert parse_lecteurs(html, 2) == [{"host": "ok.tld", "src": "https://ok.tld/v"}]


def test_parse_lecteurs_multiplexes_arrays_in_sorted_key_order():
    """Multiple eps arrays (declared out of order) yield hosts sorted by key."""
    html = (
        'var eps2 = ["https://b.tld/2"] ; '
        'var eps1 = ["https://a.tld/1"]'
    )
    hosts = [lec["host"] for lec in parse_lecteurs(html, 1)]
    assert hosts == ["a.tld", "b.tld"]


def test_extraire_eps_arrays_preserves_empty_slots_for_alignment():
    """Empty/null slots are kept as '' so the positional episode->index mapping
    holds. A hole in one lecteur must NOT shift later episodes' URLs.
    (regression: re-zero S4 had eps3 ep7='' which dropped ep11's lecteur 3.)"""
    assert _extraire_eps_arrays('var eps1 = ["u1", "", null]') == {"eps1": ["u1", "", ""]}


def test_parse_lecteurs_empty_slot_does_not_shift_later_episodes():
    """ep2 has a hole; ep3 must still resolve to its OWN url (index not shifted)."""
    html = 'var eps1 = ["https://a.tld/1","","https://a.tld/3"]'
    assert parse_lecteurs(html, 2) == []
    assert parse_lecteurs(html, 3) == [{"host": "a.tld", "src": "https://a.tld/3"}]


def test_extraire_eps_arrays_skips_malformed_array():
    """A malformed/unterminated JS array is absent from the result."""
    assert _extraire_eps_arrays("var eps2 = [bad") == {}


def test_extraire_eps_arrays_caps_at_max():
    """No more than MAX_EPS_ARRAYS arrays are extracted from hostile HTML."""
    decls = " ; ".join(f'var eps{n}=["u{n}"]' for n in range(1, 26))
    result = _extraire_eps_arrays(decls)
    assert len(result) == MAX_EPS_ARRAYS


@pytest.mark.parametrize(
    "txt,start,expected",
    [
        ('x = ["a]b", "c"]', 4, '["a]b", "c"]'),
        ("y = ['a']", 4, "['a']"),
    ],
)
def test_extraire_tableau_js_balances_brackets_inside_strings(txt, start, expected):
    """A ']' or quote inside a string must not terminate the array early."""
    assert _extraire_tableau_js(txt, start) == expected


def test_extraire_tableau_js_returns_none_without_bracket():
    """No opening bracket after start yields None."""
    assert _extraire_tableau_js("no bracket here", 0) is None


def test_parse_episodes_counts_and_builds_ep_urls():
    """Three eps map to total 3 with ?ep= URLs and saison/lang from the url."""
    html = '<html><body><script>var eps1=["u1","u2","u3"]</script></body></html>'
    saison_url = "https://anime-sama.to/catalogue/x/saison2/vostfr"
    result = parse_episodes(html, saison_url)
    assert result["total"] == 3
    assert result["langues"] == ["VOSTFR"]
    assert result["episodes"][0]["url"] == (
        "https://anime-sama.to/catalogue/x/saison2/vostfr?ep=1"
    )
    assert result["episodes"][0]["saison"] == 2


def test_parse_episodes_empty_html_returns_zero():
    """Empty HTML returns total 0 and no episodes."""
    result = parse_episodes("", "https://anime-sama.to/catalogue/x/saison2/vostfr")
    assert result["total"] == 0
    assert result["episodes"] == []


def test_parse_episodes_small_gap_arrays_win():
    """A select with 2 extra options (gap within 3) keeps the array count."""
    arr = ",".join(f'"u{i}"' for i in range(10))
    html = f"<script>var eps1=[{arr}]</script>{_select_options(12)}"
    result = parse_episodes(html, "https://anime-sama.to/catalogue/x/saison1/vostfr")
    assert result["total"] == 10


def test_parse_episodes_large_gap_takes_max():
    """A select far larger than the arrays (gap > 3) uses the max count."""
    arr = ",".join(f'"u{i}"' for i in range(5))
    html = f"<script>var eps1=[{arr}]</script>{_select_options(12)}"
    result = parse_episodes(html, "https://anime-sama.to/catalogue/x/saison1/vostfr")
    assert result["total"] == 12


def test_parse_episodes_select_only_counts_options():
    """With no eps arrays the total equals the select option count."""
    html = _select_options(7)
    result = parse_episodes(html, "https://anime-sama.to/catalogue/x/saison1/vostfr")
    assert result["total"] == 7


def test_parse_episodes_truncates_above_2000():
    """A select with 2500 options is capped to 2000 episodes."""
    html = _select_options(2500)
    result = parse_episodes(html, "https://anime-sama.to/catalogue/x/saison1/vostfr")
    assert result["total"] == 2000
    assert len(result["episodes"]) == 2000


def test_parse_episodes_title_from_titre_oeuvre_then_title_tag():
    """Titre prefers id=titreOeuvre, else strips the <title> prefix."""
    by_id = parse_episodes(
        f'<div id="titreOeuvre">One Piece</div>{_select_options(3)}',
        "https://anime-sama.to/catalogue/x/saison1/vostfr",
    )
    by_title = parse_episodes(
        f"<title>Anime-Sama - Naruto</title>{_select_options(3)}",
        "https://anime-sama.to/catalogue/x/saison1/vostfr",
    )
    assert by_id["titre"] == "One Piece"
    assert by_title["titre"] == "Naruto"


def test_parse_saisons_dedup_sort_and_lang_default():
    """Seasons are deduped, sorted by number, lang lowercased or defaulted."""
    html = (
        '<a href="/catalogue/x/saison2/vostfr">s2</a>'
        '<a href="/catalogue/x/saison1/vf">s1</a>'
        '<a href="/catalogue/x/saison2/vostfr">dup</a>'
        '<a href="/catalogue/x/saison3">s3</a>'
    )
    saisons = parse_saisons(html)
    assert saisons == [
        {"saison": 1, "url": SITE_URL + "/catalogue/x/saison1/vf", "lang": "vf"},
        {"saison": 2, "url": SITE_URL + "/catalogue/x/saison2/vostfr", "lang": "vostfr"},
        {"saison": 3, "url": SITE_URL + "/catalogue/x/saison3", "lang": "vostfr"},
    ]


def test_parse_search_results_strips_lang_suffix_from_heading():
    """A heading like 'Naruto VOSTFR' yields nom 'Naruto'."""
    results = parse_search_results('<a href="/catalogue/naruto"><h2>Naruto VOSTFR</h2></a>')
    assert results[0]["nom"] == "Naruto"


def test_parse_search_results_skips_ui_garbage_falls_back_to_slug():
    """A 'Filtrer' label is rejected as UI garbage; name falls back to slug."""
    results = parse_search_results('<a href="/catalogue/naruto"><span>Filtrer</span></a>')
    assert results[0]["nom"] == "Naruto"


def test_parse_search_results_dedupes_duplicate_slugs():
    """Duplicate slugs collapse to a single result."""
    html = (
        '<a href="/catalogue/naruto"><h2>Naruto</h2></a>'
        '<a href="/catalogue/naruto"><h2>Naruto Dup</h2></a>'
    )
    assert len(parse_search_results(html)) == 1


def test_parse_search_results_image_from_data_src():
    """When src is absent, data-src supplies the image URL."""
    html = (
        '<a href="/catalogue/naruto"><h2>Naruto</h2>'
        '<img data-src="https://cdn/x.jpg"></a>'
    )
    assert parse_search_results(html)[0]["image"] == "https://cdn/x.jpg"


def test_parse_search_results_image_fallback_to_covers_base():
    """With no img element the cover URL is built from COVERS_BASE and slug."""
    html = '<a href="/catalogue/naruto"><h2>Naruto</h2></a>'
    assert parse_search_results(html)[0]["image"] == f"{COVERS_BASE}/naruto.jpg"


def test_parse_search_results_badge_sets_uppercased_statut():
    """A badge element sets statut uppercased."""
    html = (
        '<a href="/catalogue/naruto"><h2>Naruto</h2>'
        '<span class="badge vostfr">vostfr</span></a>'
    )
    assert parse_search_results(html)[0]["statut"] == "VOSTFR"


def test_parse_search_results_nested_path_keeps_first_slug_segment():
    """The slug regex stops at the first '/', so /catalogue/a/b keeps slug 'a'.

    Pins current behavior: the '/' in slug guard is unreachable for hrefs
    because the regex group never captures a slash.
    """
    results = parse_search_results('<a href="/catalogue/a/b"><h2>Nested</h2></a>')
    assert len(results) == 1
    assert results[0]["image"] == f"{COVERS_BASE}/a.jpg"


@pytest.mark.parametrize(
    "href,expected",
    [
        ('/catalogue/x/saison1', {"has_anime": True, "has_scan": False}),
        ('/catalogue/x/scan2/', {"has_anime": False, "has_scan": True}),
        ('/catalogue/x/scan', {"has_anime": False, "has_scan": True}),
        ('/catalogue/x', {"has_anime": False, "has_scan": False}),
    ],
)
def test_detecter_type_contenu_classifies_links(href, expected):
    """Anime vs scan content is detected from anchor href shapes."""
    assert detecter_type_contenu(f'<a href="{href}">a</a>') == expected


def test_detecter_type_contenu_empty_html_both_false():
    """Empty HTML reports neither content type."""
    assert detecter_type_contenu("") == {"has_anime": False, "has_scan": False}


@pytest.mark.parametrize(
    "html,expected",
    [
        ("window.ASN_USER_ID = 4242", True),
        ("window.ASN_USER_ID = abc", False),
        ("", False),
    ],
)
class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


def test_get_lecteurs_async_normalizes_url_and_returns_requested_ep(monkeypatch):
    """The query/trailing slash are stripped and ep 2 maps to host 'b.tld'."""
    recorded: dict = {}

    async def fake_http_get(url, cookies):
        recorded["url"] = url
        recorded["cookies"] = cookies
        return _FakeResp('var eps1=["https://a.tld/1","https://b.tld/2"]')

    from engine.auth.manager import auth_manager

    monkeypatch.setattr(players_mod, "http_get", fake_http_get)
    monkeypatch.setattr(auth_manager, "cookies", [{"name": "sess", "value": "abc"}])

    result = asyncio.run(
        players_mod.get_lecteurs_async("/catalogue/x/saison1/vostfr?ep=2")
    )

    assert recorded["url"] == SITE_URL + "/catalogue/x/saison1/vostfr"
    assert recorded["cookies"] == [{"name": "sess", "value": "abc"}]
    assert result == [{"host": "b.tld", "src": "https://b.tld/2"}]


def test_get_lecteurs_async_unsafe_url_returns_empty_without_fetch(monkeypatch):
    """An off-site URL is rejected before http_get is ever called."""
    called = {"flag": False}

    async def fake_http_get(url, cookies):
        called["flag"] = True
        return _FakeResp("")

    monkeypatch.setattr(players_mod, "http_get", fake_http_get)

    result = asyncio.run(players_mod.get_lecteurs_async("https://evil.com/x?ep=1"))

    assert result == []
    assert called["flag"] is False
