import pytest

from engine.domain.exceptions import UnsafeUrlError
from engine.utils.security import (
    is_safe_url,
    sanitize_filename,
    validate_external_url,
)


def test_rejects_non_http_scheme():
    with pytest.raises(UnsafeUrlError):
        validate_external_url("file:///etc/passwd")

def test_rejects_localhost():
    assert is_safe_url("http://localhost/x") is False
    assert is_safe_url("http://127.0.0.1/x") is False

def test_rejects_private_ip():
    assert is_safe_url("http://192.168.1.10/v.m3u8") is False
    assert is_safe_url("http://10.0.0.5/v.m3u8") is False

def test_rejects_cloud_metadata():
    assert is_safe_url("http://169.254.169.254/latest/meta-data") is False

def test_accepts_public_host():
    assert is_safe_url("https://example.com/video.m3u8") is True

def test_sanitize_strips_path_separators():
    out = sanitize_filename("../../etc/passwd")
    assert "/" not in out and ".." not in out

def test_sanitize_empty_returns_unnamed():
    assert sanitize_filename("") == "unnamed"

def test_sanitize_length_capped():
    assert len(sanitize_filename("a" * 500)) <= 200
