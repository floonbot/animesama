"""Regression: redact_url must also drop a bare fragment and strip userinfo
credentials, not only the query string. Previously a secret in userinfo
(user:pass@host) or in a fragment without a query survived into logs.
"""

from engine.observability.redact import redact_url


def test_userinfo_credentials_stripped():
    out = redact_url("https://user:s3cr3tPassw0rd24chars@cdn.example.com/v.m3u8")
    assert out == "https://cdn.example.com/v.m3u8"
    assert "s3cr3tPassw0rd24chars" not in out


def test_bare_fragment_stripped():
    assert redact_url("https://host/v.m3u8#sig=SECRETVALUE") == "https://host/v.m3u8"


def test_at_sign_in_path_is_preserved():
    url = "https://host/a@b/c.mp4"
    assert redact_url(url) == url
