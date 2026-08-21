import engine.download.interceptor as ic
from engine.download.interceptor import _meilleur_resultat


def test_meilleur_resultat_prefers_m3u8():
    res = [{"url": "http://h/a.txt"}, {"url": "http://h/b.m3u8"}, {"url": "http://h/c.mp4"}]
    assert _meilleur_resultat(res)["url"] == "http://h/b.m3u8"

def test_meilleur_resultat_txt_fallback():
    res = [{"url": "http://h/c.mp4"}, {"url": "http://h/a.txt"}]
    assert _meilleur_resultat(res)["url"] == "http://h/a.txt"

def test_meilleur_resultat_first_otherwise():
    res = [{"url": "http://h/c.mp4"}, {"url": "http://h/d.bin"}]
    assert _meilleur_resultat(res)["url"] == "http://h/c.mp4"

def test_meilleur_resultat_empty_is_none():
    assert _meilleur_resultat([]) is None

def test_est_bruit_attendu_known_exception_name():
    if ic._NOISE_EXC_NAMES:
        name = next(iter(ic._NOISE_EXC_NAMES))
        exc = type(name, (Exception,), {})()
        assert ic._est_bruit_attendu({"exception": exc}) is True

def test_est_bruit_attendu_message_pattern():
    if ic._NOISE_MSG_PATTERNS:
        pat = next(iter(ic._NOISE_MSG_PATTERNS))
        assert ic._est_bruit_attendu({"message": f"prefix {pat} suffix"}) is True

def test_est_bruit_attendu_target_closed():
    assert ic._est_bruit_attendu({"message": "got TargetClosedError now"}) is True

def test_est_bruit_attendu_benign_is_false():
    assert ic._est_bruit_attendu({"message": "tout va bien", "exception": None}) is False
