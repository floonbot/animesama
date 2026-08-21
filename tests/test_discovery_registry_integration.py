"""Integration discovery -> registry : une page saison synthetique (structure
`var epsN=[...]` reelle d'Anime-Sama, domaines declares du registre, aucun token
live/jetable) doit etre classee par hote vers le bon extracteur, l'hote inconnu
retombant sur le filet generique."""

from engine.download.extractor.registry import canonical_host, get_extractor
from engine.scraping.parser.players import parse_lecteurs

SEASON_HTML = (
    'var eps1 = ["https://video.sibnet.ru/shell.php?videoid=1"];'
    'var eps2 = ["https://vidmoly.to/embed-aaa.html"];'
    'var eps3 = ["https://d000d.com/e/bbb"];'
    'var eps4 = ["https://myvi.tv/embed/ccc"];'
    'var eps5 = ["https://newhost.example/watch/ddd"]'
)


def test_season_page_hosts_resolve_to_expected_extractors():
    lecteurs = parse_lecteurs(SEASON_HTML, 1)
    resolved = {lec["host"]: get_extractor(lec["src"]).name for lec in lecteurs}
    assert resolved == {
        "video.sibnet.ru": "sibnet",
        "vidmoly.to": "vidmoly",
        "d000d.com": "doodstream",
        "myvi.tv": "myvi",
        "newhost.example": "generic",
    }


def test_season_page_unknown_host_falls_to_generic_net():
    lecteurs = parse_lecteurs(SEASON_HTML, 1)
    unknown = [lec for lec in lecteurs if get_extractor(lec["src"]).name == "generic"]
    assert [lec["host"] for lec in unknown] == ["newhost.example"]


def test_myvi_subdomains_resolve_and_inject_referer():
    assert canonical_host("myvi.tv") == "myvi"
    assert canonical_host("myvi.top") == "myvi"
    ext = get_extractor("https://myvi.top/embed/x")
    assert ext.name == "myvi" and ext.referer == "https://myvi.ru/"
