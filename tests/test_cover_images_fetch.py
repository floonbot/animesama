import builtins
import io
import os

import pytest
import requests

import engine.cache.cover_images as ci


@pytest.fixture(autouse=True)
def _reset_inflight():
    snap = set(ci._inflight)
    ci._inflight.clear()
    yield
    ci._inflight.clear()
    ci._inflight.update(snap)


@pytest.fixture(autouse=True)
def _allow_all_urls(monkeypatch):
    monkeypatch.setattr(ci, "is_safe_url", lambda _u: True)


class _Resp:
    def __init__(self, content_type, chunks, ok=True, iter_raises=False):
        self.ok = ok
        self.status_code = 200 if ok else 500
        self.headers = {"Content-Type": content_type} if content_type is not None else {}
        self._chunks = chunks
        self._iter_raises = iter_raises
        self.closed = False

    def iter_content(self, _n):
        if self._iter_raises:
            raise requests.exceptions.ChunkedEncodingError("stream broke")
        yield from self._chunks

    def close(self):
        self.closed = True


def _png_bytes(width, height, color="blue"):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


def test_fetch_request_exception_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)

    def _boom(*a, **k):
        raise requests.exceptions.ConnectTimeout("nope")

    monkeypatch.setattr(ci.requests, "get", _boom)
    assert ci.fetch_and_store("https://cdn.example.com/x.jpg") is None
    assert list(tmp_path.iterdir()) == []


def test_fetch_not_ok_status_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    resp = _Resp("image/jpeg", [b"data"], ok=False)
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)
    assert ci.fetch_and_store("https://cdn.example.com/x.jpg") is None
    assert resp.closed is True
    assert list(tmp_path.iterdir()) == []


def test_fetch_missing_content_type_header_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    resp = _Resp(None, [b"data"])
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)
    assert ci.fetch_and_store("https://cdn.example.com/x.jpg") is None
    assert resp.closed is True


def test_fetch_content_type_with_charset_is_parsed(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "_maybe_resize", lambda data, ext: (data, ext))
    resp = _Resp("image/JPEG; charset=binary", [b"JFIF-bytes"])
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)
    url = "https://cdn.example.com/photo"
    p = ci.fetch_and_store(url)
    assert p is not None and p.suffix == ".jpg"
    assert p == (tmp_path / ci._key(url)).with_suffix(".jpg")
    assert p.read_bytes() == b"JFIF-bytes"


def test_fetch_webp_extension_from_table(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "_maybe_resize", lambda data, ext: (data, ext))
    resp = _Resp("image/webp", [b"WEBP", b"data"])
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)
    p = ci.fetch_and_store("https://cdn.example.com/c.webp")
    assert p.suffix == ".webp"
    assert p.read_bytes() == b"WEBPdata"


def test_fetch_gif_extension_from_table(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "_maybe_resize", lambda data, ext: (data, ext))
    resp = _Resp("image/gif", [b"GIF89a"])
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)
    p = ci.fetch_and_store("https://cdn.example.com/c.gif")
    assert p.suffix == ".gif"


def test_fetch_iter_content_request_exception_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    resp = _Resp("image/png", [], iter_raises=True)
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)
    assert ci.fetch_and_store("https://cdn.example.com/c.png") is None
    assert resp.closed is True
    assert list(tmp_path.iterdir()) == []


def test_fetch_store_oserror_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "_maybe_resize", lambda data, ext: (data, ext))
    resp = _Resp("image/png", [b"PNGDATA"])
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)

    def _boom(_src, _dst):
        raise OSError("read-only fs")

    monkeypatch.setattr(ci.os, "replace", _boom)
    url = "https://cdn.example.com/store.png"
    assert ci.fetch_and_store(url) is None
    assert (tmp_path / ci._key(url)).with_suffix(".png") not in list(tmp_path.iterdir())


def test_fetch_calls_evict_after_store(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "_maybe_resize", lambda data, ext: (data, ext))
    evicted = []
    monkeypatch.setattr(ci, "_evict_old_files", lambda: evicted.append(True))
    resp = _Resp("image/png", [b"PNGDATA"])
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)
    p = ci.fetch_and_store("https://cdn.example.com/ev.png")
    assert p is not None and p.exists()
    assert evicted == [True]


def test_maybe_resize_small_image_unchanged():
    data = _png_bytes(100, 50)
    out, ext = ci._maybe_resize(data, ".png")
    assert out == data
    assert ext == ".png"


def test_maybe_resize_at_max_width_unchanged():
    data = _png_bytes(ci.MAX_WIDTH, 200)
    out, ext = ci._maybe_resize(data, ".png")
    assert out == data
    assert ext == ".png"


def test_maybe_resize_oversize_is_downscaled_to_jpeg():
    from PIL import Image

    data = _png_bytes(800, 400)
    out, ext = ci._maybe_resize(data, ".png")
    assert ext == ".jpg"
    assert out != data
    im = Image.open(io.BytesIO(out))
    assert im.width == ci.MAX_WIDTH
    assert im.height == int(400 * (ci.MAX_WIDTH / 800))


def test_maybe_resize_too_many_pixels_returns_unchanged(monkeypatch):
    monkeypatch.setattr(ci, "MAX_PIXELS", 100)
    data = _png_bytes(800, 400)
    out, ext = ci._maybe_resize(data, ".png")
    assert out == data
    assert ext == ".png"


def test_maybe_resize_rgba_source_converted_and_downscaled():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (720, 360), (10, 20, 30, 128)).save(buf, "PNG")
    data = buf.getvalue()
    out, ext = ci._maybe_resize(data, ".png")
    assert ext == ".jpg"
    im = Image.open(io.BytesIO(out))
    assert im.mode == "RGB"
    assert im.width == ci.MAX_WIDTH


def test_maybe_resize_import_error_returns_data_unchanged(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("PIL unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    out, ext = ci._maybe_resize(b"not-a-real-image", ".webp")
    assert out == b"not-a-real-image"
    assert ext == ".webp"


def test_maybe_resize_unparseable_data_returns_unchanged():
    out, ext = ci._maybe_resize(b"definitely-not-an-image", ".gif")
    assert out == b"definitely-not-an-image"
    assert ext == ".gif"


def test_evict_old_files_swallows_iterdir_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    survivor = tmp_path / "keep.jpg"
    survivor.write_bytes(b"x")

    def _boom(*a, **k):
        raise OSError("scandir failed")

    monkeypatch.setattr(ci.os, "scandir", _boom)
    assert ci._evict_old_files() is None
    assert survivor.exists()


def test_evict_old_files_unlink_oserror_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "MAX_FILES", 1)
    for i in range(3):
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))

    real_unlink = ci.Path.unlink

    def _maybe_fail(self, *a, **k):
        if self.name == "f0.jpg":
            raise OSError("locked")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(ci.Path, "unlink", _maybe_fail)
    ci._evict_old_files()
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == ["f0.jpg", "f2.jpg"]


def test_fetch_full_pipeline_resizes_and_stores(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    big = _png_bytes(900, 450)
    resp = _Resp("image/png", [big[:50], big[50:]])
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: resp)
    url = "https://cdn.example.com/poster.png"
    p = ci.fetch_and_store(url)
    assert p is not None and p.exists()
    assert p.suffix == ".jpg"
    assert p == (tmp_path / ci._key(url)).with_suffix(".jpg")

    from PIL import Image

    im = Image.open(io.BytesIO(p.read_bytes()))
    assert im.width == ci.MAX_WIDTH
