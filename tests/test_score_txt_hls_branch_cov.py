from engine.download.extractor import browser_extractor as be


def test_txt_hls_playlist_beats_ad_mp4():
    for txt in (
        "https://cdn/master.txt",
        "https://cdn/index-v1.txt?t=1",
        "https://cdn/secure/12/index-v1.txt",
    ):
        assert be._score_url(txt, "cdp_response") > be._score_url(
            "https://ads/blob/video.mp4", "cdp_response"
        )


def test_plain_txt_not_stream_gets_no_hls_boost():
    assert be._score_url("https://cdn/readme.txt", "") == 0


def test_m3u8_url_unaffected_by_txt_clause():
    assert be._score_url("https://cdn/secure/1/master.m3u8", "perf_resource") == (
        be._SCORE_M3U8 + be._SCORE_MASTER + be._SCORE_SECURE + be._SCORE_PERF
    )
