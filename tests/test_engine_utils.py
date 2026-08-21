
from engine.download import _engine_utils as u


def test_est_url_http():
    assert u.est_url_http("https://a.com") is True
    assert u.est_url_http("http://a.com") is True
    assert u.est_url_http("ftp://a.com") is False
    assert u.est_url_http("") is False
    assert u.est_url_http(None) is False

def test_safe_header_strips_crlf_null():
    assert u.safe_header("a\r\nb\0c") == "abc"
    assert u.safe_header("  x  ") == "x"
    assert u.safe_header(None) == ""

def test_safe_callback_invokes_and_swallows():
    seen = []
    u.safe_callback(lambda p, l: seen.append((p, l)), 50, "ligne")
    assert seen == [(50, "ligne")]
    u.safe_callback(None, 1, "x")
    def boom(p, l):
        raise RuntimeError("x")
    u.safe_callback(boom, 1, "x")

def test_supprimer_silencieux(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    u.supprimer_silencieux(str(f))
    assert not f.exists()
    u.supprimer_silencieux(str(tmp_path / "absent.txt"))

def test_fmt_speed_boundaries():
    assert u.fmt_speed(0) == "—"
    assert u.fmt_speed(-5) == "—"
    assert u.fmt_speed(2_000_000) == "2.0 MB/s"
    assert u.fmt_speed(2_000) == "2 KB/s"
    assert u.fmt_speed(500) == "500 B/s"

def test_fmt_eta_boundaries():
    assert u.fmt_eta(0) == ""
    assert u.fmt_eta(45) == "45s"
    assert u.fmt_eta(125) == "2m05s"
    assert u.fmt_eta(3661) == "1h01m"
