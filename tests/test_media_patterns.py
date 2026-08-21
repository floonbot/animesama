from engine.download._patterns import media_kind, url_a_ignorer, url_est_stream


def test_url_est_stream_accepts_direct_mp4():
    assert url_est_stream("https://cdn.host/video/file.mp4") is True
    assert url_est_stream("https://cdn.host/video/file.mp4?token=abc") is True

def test_url_est_stream_accepts_dash_mpd():
    assert url_est_stream("https://cdn.host/manifest.mpd") is True
    assert url_est_stream("https://cdn.host/manifest.mpd?v=2") is True

def test_url_est_stream_still_rejects_plain_page():
    assert url_est_stream("https://host/index.html") is False
    assert url_est_stream("https://host/script.js") is False

def test_mp4_ad_still_ignored_by_denylist():
    assert url_a_ignorer("https://host/blank.mp4") is True
    assert url_a_ignorer("https://doubleclick.net/preroll.mp4") is True

def test_media_kind_classifies():
    assert media_kind("https://cdn/master.m3u8") == "hls"
    assert media_kind("https://cdn/hls2/seg") == "hls"
    assert media_kind("https://cdn/manifest.mpd") == "dash"
    assert media_kind("https://cdn/movie.mp4?x=1") == "mp4"
    assert media_kind("https://host/index.html") is None

def test_media_kind_prefers_hls_over_mp4_segment_naming():
    assert media_kind("https://cdn/master.m3u8") == "hls"
