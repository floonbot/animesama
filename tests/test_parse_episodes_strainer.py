"""Characterization tests for parse_episodes title/option extraction.

parse_episodes only consults a handful of nodes (the title element, the
#titreOeuvre element whatever its tag, and the #selectEpisodes <option>
children). These tests pin that contract across tag shapes so a partial-parse
(SoupStrainer) optimization stays byte-identical to the full-document parse.
Fixtures are inline HTML; fully deterministic, no I/O.
"""

import pytest

from engine.scraping.parser.episodes import parse_episodes

_URL = "https://anime-sama.to/catalogue/x/saison1/vostfr"


def _options(n: int) -> str:
    return '<select id="selectEpisodes">' + "".join(f"<option>E{i}</option>" for i in range(n)) + "</select>"


@pytest.mark.parametrize(
    "titre_html,expected",
    [
        ('<div id="titreOeuvre">One Piece</div>', "One Piece"),
        ('<h1 id="titreOeuvre">Bleach</h1>', "Bleach"),
        ('<span id="titreOeuvre">Naruto Shippuden</span>', "Naruto Shippuden"),
        ('<div id="titreOeuvre">Fruits &amp; Légumes</div>', "Fruits & Légumes"),
    ],
)
def test_titre_from_titreoeuvre_any_tag(titre_html, expected):
    """The #titreOeuvre text is extracted regardless of its tag, entities decoded."""
    result = parse_episodes(f"{titre_html}{_options(3)}", _URL)
    assert result["titre"] == expected


def test_titre_falls_back_to_title_tag_stripping_prefix():
    """With no #titreOeuvre, the <title> is used and the site prefix stripped."""
    result = parse_episodes(f"<title>Anime-Sama - Death Note</title>{_options(3)}", _URL)
    assert result["titre"] == "Death Note"


def test_titreoeuvre_takes_precedence_over_title_tag():
    """When both exist, #titreOeuvre wins over <title>."""
    html = f'<title>Anime-Sama - Ignored</title><div id="titreOeuvre">Chosen</div>{_options(2)}'
    assert parse_episodes(html, _URL)["titre"] == "Chosen"


def test_option_count_ignores_options_outside_target_select():
    """Only <option>s inside #selectEpisodes are counted, not stray ones."""
    html = (
        "<select id='other'><option>x</option><option>y</option></select>"
        f"{_options(5)}"
        "<option>orphan</option>"
    )
    assert parse_episodes(html, _URL)["total"] == 5


def test_eps_arrays_and_select_gap_reconciliation_preserved():
    """The eps[]-vs-select reconciliation (small gap keeps arrays) is unchanged."""
    arr = ",".join(f'"u{i}"' for i in range(10))
    html = f"<script>var eps1=[{arr}]</script>{_options(12)}"
    assert parse_episodes(html, _URL)["total"] == 10


def test_title_with_nested_markup_text_is_flattened():
    """Nested markup inside #titreOeuvre is flattened via get_text(strip=True)."""
    html = f'<div id="titreOeuvre">My <b>Hero</b> Academia</div>{_options(3)}'
    assert parse_episodes(html, _URL)["titre"] == "MyHeroAcademia"
