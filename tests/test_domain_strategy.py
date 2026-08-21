from engine.download._domain_strategy import (
    get_domain,
    lecteur_url_valide,
    partition_lecteurs,
    strategie_lecteur,
)


def test_get_domain():
    assert get_domain("https://www.sendvid.com/abc") == "www.sendvid.com"
    assert get_domain("") == ""

def test_invalid_player_rejected():
    assert lecteur_url_valide({"src": ""}) is False
    assert lecteur_url_valide({"src": "notaurl"}) is False
    assert lecteur_url_valide({"src": "https://x.com/a"}) is True

def test_strategy_ytdlp_first_for_known_domain():
    assert strategie_lecteur({"src": "https://sendvid.com/v"}) == "ytdlp_first"

def test_strategy_default_playwright():
    assert strategie_lecteur({"src": "https://unknown-host.tld/v"}) == "playwright_first"

def test_partition_splits_and_filters():
    lecteurs = [
        {"src": "https://sendvid.com/a"},
        {"src": "https://unknown.tld/b"},
        {"src": ""},
    ]
    ytdlp, autres = partition_lecteurs(lecteurs)
    assert len(ytdlp) == 1
    assert len(autres) == 1
