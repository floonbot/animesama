"""Regression for two parser hardening fixes:

- profile.py: the favorite-URL guard was a SITE_URL substring test, so a forged
  off-site URL embedding SITE_URL in its query (https://evil/?x=<SITE_URL>) passed.
  It now compares the URL's netloc (origin) to the site's netloc.
- episodes.py: parse_episodes joined a scheme-less relative saison_url as
  SITE_URL + base (no separator) → https://anime-sama.tocatalogue/... for a
  no-leading-slash base. It now joins SITE_URL + "/" + base.lstrip("/").
"""

from engine.scraping.parser.episodes import parse_episodes
from engine.scraping.parser.profile import parse_favoris_api
from engine.scraping.site.animessama import SITE_URL


def test_parse_favoris_api_drops_forged_substring_url():
    data = {"favorites": {"url": ["https://evil.example/?x=" + SITE_URL], "nom": ["x"], "img": [""]}}
    assert parse_favoris_api(data) == []


def test_parse_favoris_api_keeps_onsite_url():
    data = {"favorites": {"url": ["/catalogue/ok"], "nom": ["OK"], "img": [""]}}
    out = parse_favoris_api(data)
    assert len(out) == 1
    assert out[0]["url"] == SITE_URL + "/catalogue/ok"


def test_parse_favoris_api_malformed_absolute_url_skips_entry_not_batch():
    data = {"favorites": {
        "url": ["http://[::1", "/catalogue/good"],
        "nom": ["Bad", "Good"],
        "img": ["", ""],
    }}
    out = parse_favoris_api(data)
    assert [f["url"] for f in out] == [SITE_URL + "/catalogue/good"]


def test_parse_episodes_relative_base_without_leading_slash():
    html = 'var eps1=["https://a.tld/1"]'
    out = parse_episodes(html, "catalogue/x/saison2/vf")
    assert out["total"] == 1
    assert out["episodes"][0]["url"] == f"{SITE_URL}/catalogue/x/saison2/vf?ep=1"
