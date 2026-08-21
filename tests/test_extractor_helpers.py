from engine.download.extractor.browser_extractor import (
    _meilleur_resultat,
    _normaliser,
    _score_url,
)


def test_normaliser_strips_fragment():
    assert _normaliser("http://h/p?q=1#frag") == "http://h/p?q=1"
    assert _normaliser("http://h/p") == "http://h/p"

def test_normaliser_bad_input_returns_input():
    assert _normaliser("pas une url") == "pas une url"

def test_score_url_m3u8_dominates():
    assert _score_url("http://h/master.m3u8", "fetch") > _score_url("http://h/video.mp4", "fetch")

def test_score_url_components_add_up():
    base = _score_url("http://h/x", "")
    assert _score_url("http://h/x.m3u8", "") == base + 100
    assert _score_url("http://h/master", "") == base + 20
    assert _score_url("http://h/hls/x", "") == base + 10
    assert _score_url("http://h/x", "cdp_request") == base + 30
    assert _score_url("http://h/x", "fetch") == base + 20
    assert _score_url("http://h/x", "dom_mutation") == base + 5

def test_meilleur_resultat_picks_highest_score():
    res = [
        {"url": "http://h/a.mp4", "type": "dom"},
        {"url": "http://h/master.m3u8", "type": "fetch"},
        {"url": "http://h/b.ts", "type": "perf"},
    ]
    assert _meilleur_resultat(res)["url"] == "http://h/master.m3u8"

def test_meilleur_resultat_empty_is_none():
    assert _meilleur_resultat([]) is None
