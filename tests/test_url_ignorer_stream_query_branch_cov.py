"""Regression: url_a_ignorer matched asset extensions (.png/.css/.js...) anywhere
in the URL, so a real stream whose query carries such a token
(master.m3u8?poster=cover.png) was wrongly dropped. Extensions are now matched
against the path only; domain/name denylist markers (tracker, doubleclick,
blank.mp4) still match anywhere.
"""

from engine.download._patterns import url_a_ignorer


def test_stream_with_image_query_param_not_ignored():
    assert url_a_ignorer("https://cdn/hls/master.m3u8?poster=cover.png") is False


def test_plain_image_asset_still_ignored():
    assert url_a_ignorer("https://host/logo.png") is True
    assert url_a_ignorer("https://host/app.css") is True
    assert url_a_ignorer("https://host/bundle.js") is True


def test_blank_mp4_placeholder_still_ignored():
    assert url_a_ignorer("https://host/blank.mp4") is True


def test_tracker_stream_still_ignored():
    assert url_a_ignorer("https://doubleclick.net/preroll.mp4") is True
