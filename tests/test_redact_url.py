from engine.observability.redact import redact_text, redact_url


def test_strips_query_string_with_token():
    url = "https://cdn.example.com/video/master.m3u8?token=SECRET123&expires=999&sig=abcdef"
    out = redact_url(url)
    assert out == "https://cdn.example.com/video/master.m3u8"
    assert "?" not in out
    assert "SECRET123" not in out
    assert "sig" not in out


def test_keeps_path_without_query_untouched():
    url = "https://cdn.example.com/a/b/c.mp4"
    assert redact_url(url) == url


def test_applies_length_limit_after_stripping_query():
    url = "https://host/" + "a" * 500 + "?token=x"
    out = redact_url(url, 40)
    assert len(out) == 40
    assert "token" not in out


def test_default_limit_is_120():
    url = "https://host/" + "p" * 500
    assert len(redact_url(url)) == 120


def test_non_string_and_empty_are_safe():
    assert redact_url(None) == ""
    assert redact_url("") == ""
    assert redact_url(12345) == "12345"


def test_fragment_after_query_removed():
    url = "https://host/path?token=SECRET#frag"
    out = redact_url(url)
    assert out == "https://host/path"
    assert "SECRET" not in out


def test_caviars_long_path_token_segment():
    out = redact_url("https://cdn.example.com/hls/AB12cd34EF56gh78IJ90kl12mn/master.m3u8")
    assert "AB12cd34EF56gh78IJ90kl12mn" not in out
    assert out.endswith("/master.m3u8")
    assert out.startswith("https://cdn.example.com/hls/")


def test_keeps_human_readable_slug_with_hyphens():
    url = "https://anime-sama.fr/catalogue/kaguya-sama-love-is-war-s3/"
    assert redact_url(url) == url


def test_caviars_base64url_path_token_with_separators():
    tok = "aB3xY9kP2-mN5_qR8wT1vU4zE7cD0gH6jL"
    out = redact_url(f"https://cdn.example.com/secure/{tok}/master.m3u8")
    assert tok not in out
    assert out.endswith("/master.m3u8")
    assert out.startswith("https://cdn.example.com/secure/")


def test_keeps_long_lowercase_slug_with_digit_and_hyphens():
    url = "https://anime-sama.fr/catalogue/kaguya-sama-love-is-war-season-3-2022/"
    assert redact_url(url) == url


def test_redact_text_scrubs_url_inside_line():
    line = "ERROR: unable to download https://cdn/v.m3u8?token=SECRET&sig=abc : HTTP 403"
    out = redact_text(line)
    assert "SECRET" not in out
    assert "sig=abc" not in out
    assert "ERROR: unable to download" in out
    assert "HTTP 403" in out


def test_redact_text_without_url_unchanged():
    assert redact_text("plain ffmpeg error, no url here") == "plain ffmpeg error, no url here"
    assert redact_text("") == ""
    assert redact_text(None) == ""
