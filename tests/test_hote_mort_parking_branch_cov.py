from engine.download.interceptor import _est_url_morte


def test_detecte_parking_ww_digit():
    assert _est_url_morte("https://ww1.oneupload.to/embed-x.html")
    assert _est_url_morte("https://ww2.something.com/")
    assert _est_url_morte("http://ww42.parked.net/page")


def test_ne_confond_pas_www_ni_hotes_legitimes():
    assert not _est_url_morte("https://www1.cdn.example/stream.m3u8")
    assert not _est_url_morte("https://www.host.com/")
    assert not _est_url_morte("https://video.sibnet.ru/v")
    assert not _est_url_morte("https://strm9.uqload.is/hls2/x/master.m3u8")
    assert not _est_url_morte("")
