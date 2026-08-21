import asyncio

from engine.download.extractor import browser_extractor as bx


def test_mp4_url_scores_mp4_bonus():
    assert bx._score_url("https://cdn/h/video.mp4", "") == bx._SCORE_MP4

def test_mpd_url_scores_dash_bonus():
    assert bx._score_url("https://cdn/h/manifest.mpd", "") == bx._SCORE_DASH

def test_m3u8_outranks_mp4():
    assert bx._score_url("https://cdn/a.m3u8", "") > bx._score_url("https://cdn/a.mp4", "")

def test_meilleur_resultat_prefers_m3u8_over_mp4():
    best = bx._meilleur_resultat([
        {"url": "https://cdn/direct.mp4", "type": "cdp_response"},
        {"url": "https://cdn/master.m3u8", "type": "cdp_response"},
    ])
    assert best["url"] == "https://cdn/master.m3u8"

def test_meilleur_resultat_returns_mp4_when_only_option():
    best = bx._meilleur_resultat([{"url": "https://cdn/only.mp4", "type": "cdp_response"}])
    assert best["url"] == "https://cdn/only.mp4"

def test_existing_m3u8_additive_score_unchanged():
    expected = bx._SCORE_M3U8 + bx._SCORE_MASTER + bx._SCORE_HLS_PATH + bx._SCORE_CDP
    assert bx._score_url("http://h/hls/master.m3u8", "cdp_response") == expected


class _FakePage:
    def __init__(self, html) -> None:
        self._html = html

    async def content(self) -> str:
        return self._html


def test_forensic_scan_extracts_direct_mp4():
    html = '<video><source src="https://cdn.example.com/movie.mp4?t=1"></video>'
    results = asyncio.run(bx._forensic_scan(_FakePage(html)))
    media = [r for r in results if r["type"] == "forensic_media"]
    assert {"url": "https://cdn.example.com/movie.mp4?t=1", "type": "forensic_media", "ts": 0} in media

def test_forensic_scan_extracts_dash_mpd():
    html = 'var src = "https://cdn.example.com/stream.mpd";'
    results = asyncio.run(bx._forensic_scan(_FakePage(html)))
    media = [r for r in results if r["type"] == "forensic_media"]
    assert any(r["url"] == "https://cdn.example.com/stream.mpd" for r in media)

def test_forensic_scan_m3u8_still_forensic_html():
    html = "watch https://cdn.example.com/master.m3u8 now"
    results = asyncio.run(bx._forensic_scan(_FakePage(html)))
    assert any(r["type"] == "forensic_html" and r["url"] == "https://cdn.example.com/master.m3u8" for r in results)
