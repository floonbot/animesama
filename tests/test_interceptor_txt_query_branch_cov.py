from engine.download.interceptor import _meilleur_resultat


def test_meilleur_resultat_txt_master_with_query_is_recognized():
    res = [
        {"url": "https://h/player.mp4"},
        {"url": "https://h/master.txt?token=abc123"},
    ]
    assert _meilleur_resultat(res)["url"] == "https://h/master.txt?token=abc123"


def test_meilleur_resultat_txt_master_with_fragment_is_recognized():
    res = [
        {"url": "https://h/player.mp4"},
        {"url": "https://h/master.txt#frag"},
    ]
    assert _meilleur_resultat(res)["url"] == "https://h/master.txt#frag"


def test_meilleur_resultat_plain_txt_still_matched():
    res = [{"url": "https://h/c.mp4"}, {"url": "https://h/a.txt"}]
    assert _meilleur_resultat(res)["url"] == "https://h/a.txt"
