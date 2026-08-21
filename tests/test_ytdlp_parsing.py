from engine.download.methods._ytdlp_parsing import (
    construire_commande,
    get_domain,
    parser_progression,
)


def _cmd(headers=None, qualite="auto", aria2c=None):
    return construire_commande("yt", "http://h/v", "/d", "n", headers or {}, qualite, aria2c)

def test_get_domain():
    assert get_domain("https://Video.Sibnet.RU/x") == "video.sibnet.ru"
    assert get_domain("notaurl") == ""

def test_quality_formats():
    assert "bestvideo[ext=mp4]" in _cmd(qualite="auto")[_cmd(qualite="auto").index("--format") + 1]
    for q in ("1080", "720", "480"):
        c = _cmd(qualite=q)
        assert f"height<={q}" in c[c.index("--format") + 1]
    c = _cmd(qualite="2160")
    assert c[c.index("--format") + 1] == "best"

def test_quality_strips_p_suffix():
    c = _cmd(qualite="720p")
    assert "height<=720" in c[c.index("--format") + 1]

def test_aria2c_added_only_when_path_given():
    assert "--downloader" not in _cmd(aria2c=None)
    c = _cmd(aria2c="/usr/bin/aria2c")
    assert "--downloader" in c and "aria2c" in c

def test_sibnet_special_headers():
    c = construire_commande("yt", "https://video.sibnet.ru/v", "/d", "n", {}, "auto")
    assert "--referer" in c and "https://video.sibnet.ru/" in c
    assert "Origin:https://video.sibnet.ru" in c
    assert "--extractor-args" in c
    assert "sibnet:quality=1080" in c

def test_referer_and_cookie_passthrough():
    c = _cmd(headers={"referer": "http://r", "cookie": "k=1"})
    assert "http://r" in c
    assert "Cookie:k=1" in c

def test_origin_fallback_for_referer():
    c = _cmd(headers={"origin": "http://o"})
    assert "http://o" in c

def test_parser_progression_full():
    out = parser_progression("[download]  42.5% of ~100.00MiB at 5.00MiB/s ETA 00:30")
    assert out[0] == 42.5
    assert "ETA 00:30" in out[1] and "5.00MiB/s" in out[1]

def test_parser_progression_simple_and_none():
    assert parser_progression("[download]   7.0%")[0] == 7.0
    assert parser_progression("autre chose") is None
