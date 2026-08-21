import os
import time
import zipfile

import pytest

import engine.scraping.scan as scan_mod
from engine.domain.exceptions import DownloadCancelled
from engine.download.methods import images


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)


class _Resp:
    def __init__(self, status_code, content_type, chunks):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type is not None else {}
        self._chunks = chunks
        self.closed = False

    def iter_content(self, n):
        yield from self._chunks

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._resp


def _two_pages(*args, **kwargs):
    return [
        {"page": 1, "url": "https://h/p1.jpg"},
        {"page": 2, "url": "https://h/p2.jpg"},
    ]


def test_scan_download_success_writes_cbz(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "get_pages_sync", _two_pages)
    monkeypatch.setattr(images, "_telecharger_image", lambda *a, **k: (b"IMG", ".jpg"))

    progress = []

    def on_progress(pct, msg):
        progress.append((pct, msg))

    result = images.scan_download(
        "oeuvre", "vf", ["1"], str(tmp_path), cancelled=None, on_progress=on_progress
    )

    expected = os.path.join(str(tmp_path), "Chapitre 1.cbz")
    assert result == expected
    assert os.path.exists(expected)

    with zipfile.ZipFile(expected, "r") as zf:
        names = zf.namelist()
        assert "001.jpg" in names
        assert "002.jpg" in names
        assert zf.read("001.jpg") == b"IMG"
        assert zf.read("002.jpg") == b"IMG"

    assert progress
    assert any("Chapitre 1" in msg for _, msg in progress)
    assert not os.path.exists(expected + ".part")


def test_scan_download_already_present_skips_fetch(tmp_path, monkeypatch):
    cbz = os.path.join(str(tmp_path), "Chapitre 1.cbz")
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("existing.txt", b"x")

    def _boom(*a, **k):
        raise AssertionError("get_pages_sync must not be called")

    monkeypatch.setattr(scan_mod, "get_pages_sync", _boom)

    progress = []
    result = images.scan_download(
        "oeuvre", "vf", ["1"], str(tmp_path),
        on_progress=lambda pct, msg: progress.append((pct, msg)),
    )

    assert result == cbz
    assert any("déjà présent" in msg for _, msg in progress)


def test_scan_download_no_pages_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "get_pages_sync", lambda *a, **k: [])
    monkeypatch.setattr(
        images, "_telecharger_image",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    result = images.scan_download("oeuvre", "vf", ["1"], str(tmp_path))

    assert result is None
    assert not os.path.exists(os.path.join(str(tmp_path), "Chapitre 1.cbz"))
    assert os.listdir(str(tmp_path)) == []


def test_scan_download_cancelled_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "get_pages_sync", _two_pages)
    monkeypatch.setattr(images, "_telecharger_image", lambda *a, **k: (b"IMG", ".jpg"))

    class _Token:
        def is_cancelled(self):
            return True

    with pytest.raises(DownloadCancelled):
        images.scan_download("oeuvre", "vf", ["1"], str(tmp_path), cancelled=_Token())

    assert not os.path.exists(os.path.join(str(tmp_path), "Chapitre 1.cbz"))


def test_scan_download_cancelled_via_list_token(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "get_pages_sync", _two_pages)
    monkeypatch.setattr(images, "_telecharger_image", lambda *a, **k: (b"IMG", ".jpg"))

    with pytest.raises(DownloadCancelled):
        images.scan_download("oeuvre", "vf", ["1"], str(tmp_path), cancelled=[True])


def test_scan_download_image_failure_skips_chapter_and_cleans_part(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "get_pages_sync", _two_pages)
    monkeypatch.setattr(images, "_telecharger_image", lambda *a, **k: None)

    result = images.scan_download("oeuvre", "vf", ["1"], str(tmp_path))

    assert result is None
    assert not os.path.exists(os.path.join(str(tmp_path), "Chapitre 1.cbz"))
    assert not os.path.exists(os.path.join(str(tmp_path), "Chapitre 1.cbz.part"))
    assert os.listdir(str(tmp_path)) == []


def test_scan_download_chapitre_rate_ne_stoppe_pas_le_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_mod, "get_pages_sync", _two_pages)

    tentes: list[str] = []

    def _dl(session, url, safe_cache=None):
        tentes.append(url)
        if "ch2" in url:
            return None
        return (b"IMG", ".jpg")

    monkeypatch.setattr(scan_mod, "get_pages_sync", lambda o, c, l: [
        {"url": f"https://h/{c}/ch{c}_p1.jpg", "page": 1},
        {"url": f"https://h/{c}/ch{c}_p2.jpg", "page": 2},
    ])
    monkeypatch.setattr(images, "_telecharger_image", _dl)

    result = images.scan_download("oeuvre", "vf", ["1", "2", "3"], str(tmp_path))

    assert os.path.exists(os.path.join(str(tmp_path), "Chapitre 1.cbz"))
    assert not os.path.exists(os.path.join(str(tmp_path), "Chapitre 2.cbz"))
    assert os.path.exists(os.path.join(str(tmp_path), "Chapitre 3.cbz"))
    assert result == os.path.join(str(tmp_path), "Chapitre 3.cbz")
    assert any("ch3" in u for u in tentes)


def test_telecharger_image_success_png(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    resp = _Resp(200, "image/png", [b"AB", b"CD"])
    session = _Session(resp)

    out = images._telecharger_image(session, "https://h/p.png")

    assert out == (b"ABCD", ".png")
    assert resp.closed is True
    assert len(session.calls) == 1


def test_telecharger_image_redirect_refused(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    resp = _Resp(302, "image/png", [b"AB"])
    session = _Session(resp)

    out = images._telecharger_image(session, "https://h/p.png")

    assert out is None
    assert resp.closed is True
    assert len(session.calls) == 1


def test_telecharger_image_404_returns_none(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    resp = _Resp(404, "image/png", [b"AB"])
    session = _Session(resp)

    out = images._telecharger_image(session, "https://h/p.png")

    assert out is None
    assert resp.closed is True
    assert len(session.calls) == 1


def test_telecharger_image_unsafe_url_no_get(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: False)
    resp = _Resp(200, "image/png", [b"AB"])
    session = _Session(resp)

    out = images._telecharger_image(session, "https://h/p.png")

    assert out is None
    assert session.calls == []


def test_telecharger_image_oversized_returns_none(monkeypatch):
    monkeypatch.setattr(images, "is_safe_url", lambda url: True)
    monkeypatch.setattr(images, "IMG_MAX_BYTES", 4)
    resp = _Resp(200, "image/png", [b"AB", b"CDE"])
    session = _Session(resp)

    out = images._telecharger_image(session, "https://h/p.png")

    assert out is None
    assert resp.closed is True
