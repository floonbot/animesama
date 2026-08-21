"""Regression: season-URL language detection must cover VA/regional dubs.

`_detecter_langue` (engine.scraping.episodes) recognises vostfr/vf/va/vkr/vcn/
vqc/vj and builds probed season URLs ending in those tokens. `_RE_LANG_URL`
(used by parse_episodes/parse_saisons) previously only matched vostfr|vf, so a
`.../saison1/va` page was mislabelled VOSTFR on every episode and facet.
"""

import pytest

from engine.scraping.episodes import _detecter_langue
from engine.scraping.parser.episodes import parse_episodes, parse_saisons

_EPS_HTML = '<html><body><script>var eps1=["u1","u2"]</script></body></html>'


@pytest.mark.parametrize(
    "token,expected",
    [
        ("vostfr", "VOSTFR"),
        ("vf", "VF"),
        ("va", "VA"),
        ("vkr", "VKR"),
        ("vcn", "VCN"),
        ("vqc", "VQC"),
        ("vj", "VJ"),
    ],
)
def test_parse_episodes_preserves_regional_language(token, expected):
    url = f"https://anime-sama.to/catalogue/x/saison1/{token}"
    result = parse_episodes(_EPS_HTML, url)
    assert result["langues"] == [expected]
    assert result["episodes"][0]["langue"] == expected


@pytest.mark.parametrize("token", ["va", "vkr", "vcn", "vqc", "vj"])
def test_parse_saisons_preserves_regional_language(token):
    href = f"/catalogue/x/saison1/{token}"
    html = f'<html><body><a href="{href}">S1</a></body></html>'
    saisons = parse_saisons(html)
    assert saisons, "season link should be parsed"
    assert saisons[0]["lang"] == token


@pytest.mark.parametrize("token", ["va", "vkr", "vcn", "vqc", "vj"])
def test_detecter_langue_and_parser_agree(token):
    """The URL builder and the parser must agree on the language token."""
    url = f"https://anime-sama.to/catalogue/x/saison1/{token}"
    assert _detecter_langue(url) == token
    assert parse_episodes(_EPS_HTML, url)["langues"] == [token.upper()]
