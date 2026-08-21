from types import SimpleNamespace

from engine.scraping import anilist
from engine.scraping.parser.episodes import parse_episodes

SAISON_URL = "https://anime-sama.to/catalogue/show/saison1/vostfr"


def _episodes_html(n_array: int, n_select: int) -> str:
    arr = "[" + ",".join(f'"u{i}"' for i in range(n_array)) + "]"
    opts = "".join("<option>x</option>" for _ in range(n_select))
    return (
        f'<html><body><h1 id="titreOeuvre">Show</h1>'
        f"<script>var eps1={arr};</script>"
        f'<select id="selectEpisodes">{opts}</select></body></html>'
    )


def test_episode_gap_of_three_keeps_array_count():
    """A select/array gap of exactly 3 stays in the small-gap branch (arrays win)."""
    result = parse_episodes(_episodes_html(10, 13), SAISON_URL)
    assert result["total"] == 10


def test_episode_gap_of_four_takes_max():
    """A gap of 4 crosses the threshold into the large-gap branch (max wins)."""
    result = parse_episodes(_episodes_html(10, 14), SAISON_URL)
    assert result["total"] == 14


def test_canon_saison1_non_match_returns_matched_false(monkeypatch):
    """A fetched media whose titles do not match yields matched=False and is still cached."""
    stored = {}
    fake_disk = SimpleNamespace(get=lambda k: None, set=lambda k, v: stored.__setitem__(k, v))
    monkeypatch.setattr(anilist, "_disk", fake_disk)
    monkeypatch.setattr(anilist, "_ENABLED", True)

    def fake_fetch(titre):
        return {"title": {"romaji": "Totally Different", "english": None}, "episodes": 12, "status": "RELEASING"}

    monkeypatch.setattr(anilist, "_fetch_sync", fake_fetch)

    result = anilist.canon_saison1("My Show")
    assert result == {"matched": False, "episodes": None, "finished": False}
    assert stored
