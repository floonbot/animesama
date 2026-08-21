import requests

from engine.download.methods import ffmpeg_engine, images, ytdlp_engine


def _boom_makedirs(path, exist_ok=False):
    raise OSError("read-only filesystem")


def test_ffmpeg_makedirs_oserror_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine.os, "makedirs", _boom_makedirs)

    assert ffmpeg_engine.ffmpeg_download("http://h/v.m3u8", str(tmp_path / "x"), "ep") is None


def test_ytdlp_makedirs_oserror_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine.os, "makedirs", _boom_makedirs)

    assert ytdlp_engine.ytdlp_download("http://h/v.m3u8", str(tmp_path / "x"), "ep") is None


def test_scan_download_makedirs_oserror_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(images.os, "makedirs", _boom_makedirs)

    out = images.scan_download("oeuvre", "vf", ["1"], str(tmp_path / "x"))

    assert out is None


class _MidStreamResp:
    def __init__(self):
        self.status_code = 200
        self.headers = {"Content-Type": "image/jpeg"}
        self.closed = False

    def iter_content(self, size):
        yield b"x" * 10
        raise requests.exceptions.ChunkedEncodingError("connection reset mid-body")

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, resp):
        self.resp = resp

    def get(self, url, **kwargs):
        return self.resp


def _raise_lookup(url):
    raise LookupError("no dns in test")


def test_image_iter_content_midstream_exception_closes_response(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda u: True)
    monkeypatch.setattr(images, "pin_target", _raise_lookup)
    monkeypatch.setattr(images, "RETRY_DELAY", 0)

    resp = _MidStreamResp()
    out = images._telecharger_image(_Session(resp), "http://host.example/p.jpg")

    assert out is None
    assert resp.closed is True
