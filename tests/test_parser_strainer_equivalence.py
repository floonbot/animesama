"""Garde-fou : le parsing partiel (SoupStrainer) reste byte-identique.

Pinne le fait que limiter la construction du soup aux seules balises
reellement consultees (`<script>` pour la library JSON, `<a>` pour les
saisons et la detection de type) ne change aucune sortie observable, et que
l'early-exit de detecter_type_contenu ne modifie pas son resultat. Inputs
inline, aucune I/O.
"""

from bs4 import BeautifulSoup, SoupStrainer

from engine.scraping.parser._base import _make_soup
from engine.scraping.parser.episodes import parse_saisons
from engine.scraping.parser.profile import detecter_type_contenu
from engine.scraping.site.animessama import SITE_URL


def _rich(body: str) -> str:
    noise = '<div class="card"><span>bruit</span><p>texte</p></div>' * 30
    return f"<html><head><style>x{{}}</style></head><body>{noise}{body}{noise}</body></html>"


def test_make_soup_parse_only_filters_non_matching_tags():
    html = '<div id="d">x</div><script>var a=1</script><a href="/y">l</a>'
    soup = _make_soup(html, parse_only=SoupStrainer("script"))
    assert [s.string for s in soup.find_all("script")] == ["var a=1"]
    assert soup.find_all("div") == []
    assert soup.find_all("a") == []


def test_make_soup_default_still_full_tree():
    html = '<div id="d">x</div><script>var a=1</script>'
    soup = _make_soup(html)
    assert soup.find(id="d").get_text() == "x"
    assert soup.find("script").string == "var a=1"




def test_parse_saisons_equivalent_to_full_soup():
    body = (
        '<a href="/catalogue/mon-anime/saison1/vostfr">S1</a>'
        '<a href="/catalogue/mon-anime/saison2/vf">S2</a>'
        '<a href="/autre/lien">bruit</a>'
    )
    html = _rich(body)

    saisons = parse_saisons(html)
    assert [s["saison"] for s in saisons] == [1, 2]
    assert saisons[0]["lang"] == "vostfr"
    assert saisons[1]["lang"] == "vf"
    assert saisons[0]["url"] == SITE_URL + "/catalogue/mon-anime/saison1/vostfr"

    full = BeautifulSoup(html, "lxml")
    full_hrefs = {a.get("href") for a in full.find_all("a", href=True) if "saison" in (a.get("href") or "")}
    assert {s["url"].replace(SITE_URL, "") for s in saisons} == full_hrefs


def test_detecter_type_contenu_both_anime_and_scan():
    body = '<a href="/catalogue/x/saison1/vostfr">a</a><a href="/catalogue/x/scan/vf">s</a>'
    assert detecter_type_contenu(_rich(body)) == {"has_anime": True, "has_scan": True}


def test_detecter_type_contenu_scan_with_digits():
    body = '<a href="/catalogue/x/scan2/vf">s</a>'
    assert detecter_type_contenu(_rich(body)) == {"has_anime": False, "has_scan": True}


def test_detecter_type_contenu_early_exit_order_independent():
    forward = '<a href="/catalogue/x/saison1/vostfr">a</a><a href="/catalogue/x/scan/vf">s</a>'
    reverse = '<a href="/catalogue/x/scan/vf">s</a><a href="/catalogue/x/saison1/vostfr">a</a>'
    assert detecter_type_contenu(_rich(forward)) == detecter_type_contenu(_rich(reverse))
    assert detecter_type_contenu(_rich(forward)) == {"has_anime": True, "has_scan": True}


def test_detecter_type_contenu_empty():
    assert detecter_type_contenu("") == {"has_anime": False, "has_scan": False}
