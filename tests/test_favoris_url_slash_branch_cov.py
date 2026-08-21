from engine.scraping.parser.episodes import parse_saisons
from engine.scraping.parser.profile import parse_favoris_api
from engine.scraping.site.animessama import SITE_URL


def _fav(url: str, nom: str = "N") -> dict:
    bloc = {"url": [url]}
    if nom is not None:
        bloc["nom"] = [nom]
    return {"favorites": bloc}


def test_parse_favoris_relative_url_without_leading_slash_keeps_separator():
    result = parse_favoris_api(_fav("catalogue/noslash"))
    assert result[0]["url"] == SITE_URL + "/catalogue/noslash"
    assert result[0]["url"].startswith(SITE_URL + "/")


def test_parse_favoris_relative_url_with_leading_slash_unchanged():
    result = parse_favoris_api(_fav("/catalogue/withslash"))
    assert result[0]["url"] == SITE_URL + "/catalogue/withslash"


def test_parse_favoris_absolute_onsite_url_untouched():
    result = parse_favoris_api(_fav(SITE_URL + "/catalogue/abs"))
    assert result[0]["url"] == SITE_URL + "/catalogue/abs"


def test_parse_favoris_trailing_slash_url_without_name_falls_back_to_slug():
    result = parse_favoris_api({"favorites": {"url": [SITE_URL + "/catalogue/one-piece/"]}})
    assert result[0]["nom"] == "one-piece"


def test_parse_saisons_relative_href_without_leading_slash_keeps_separator():
    saisons = parse_saisons('<a href="catalogue/x/saison1/vf">S1</a>')
    assert saisons[0]["url"] == SITE_URL + "/catalogue/x/saison1/vf"
    assert saisons[0]["url"].startswith(SITE_URL + "/")


def test_parse_saisons_href_with_leading_slash_unchanged():
    saisons = parse_saisons('<a href="/catalogue/x/saison2/vostfr">S2</a>')
    assert saisons[0]["url"] == SITE_URL + "/catalogue/x/saison2/vostfr"
