from engine.download.interceptor import _meilleur_resultat


def test_prefers_real_master_over_preload_decoy():
    res = [
        {"url": "https://cdn/preload.m3u8", "type": "hls"},
        {"url": "https://cdn/master.m3u8", "type": "hls"},
    ]
    assert _meilleur_resultat(res)["url"] == "https://cdn/master.m3u8"


def test_falls_back_to_first_m3u8_when_all_decoys():
    res = [
        {"url": "https://cdn/preload.m3u8"},
        {"url": "https://cdn/blank.m3u8"},
    ]
    assert _meilleur_resultat(res)["url"] == "https://cdn/preload.m3u8"


def test_non_decoy_m3u8_still_preferred_over_txt():
    res = [
        {"url": "https://cdn/a.txt"},
        {"url": "https://cdn/b.m3u8"},
    ]
    assert _meilleur_resultat(res)["url"] == "https://cdn/b.m3u8"


def test_empty_is_none():
    assert _meilleur_resultat([]) is None
