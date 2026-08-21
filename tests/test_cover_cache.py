import engine.cache.cover_images as ci


def test_key_is_stable_and_hex():
    k = ci._key("https://example.com/a.jpg")
    assert k == ci._key("https://example.com/a.jpg")
    assert len(k) == 40 and all(c in "0123456789abcdef" for c in k)

def test_cached_file_none_when_absent():
    assert ci.cached_file("https://example.com/does-not-exist-xyz.jpg") is None

def test_fetch_rejects_unsafe_url(monkeypatch):
    called = {"n": 0}

    def _fake_get(*a, **k):
        called["n"] += 1
        raise AssertionError("should not fetch an unsafe URL")

    monkeypatch.setattr(ci.requests, "get", _fake_get)
    assert ci.fetch_and_store("http://127.0.0.1/x.jpg") is None
    assert called["n"] == 0

def test_fetch_and_store_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "is_safe_url", lambda u: True)

    class _Resp:
        ok = True
        status_code = 200
        headers ={"Content-Type": "image/png"}

        def iter_content(self, _n):
            yield b"\x89PNG\r\n\x1a\n" + b"x" * 100

        def close(self):
            pass

    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: _Resp())
    p = ci.fetch_and_store("https://cdn.example.com/cover.png")
    assert p is not None and p.exists()
    assert ci.cached_file("https://cdn.example.com/cover.png") == p

def test_fetch_rejects_non_image(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "is_safe_url", lambda u: True)

    class _Resp:
        ok = True
        status_code = 200
        headers ={"Content-Type": "text/html"}

        def iter_content(self, _n):
            yield b"<html>"

        def close(self):
            pass

    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: _Resp())
    assert ci.fetch_and_store("https://evil.example.com/page") is None

def test_fetch_enforces_size_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "is_safe_url", lambda u: True)
    monkeypatch.setattr(ci, "MAX_BYTES", 10)

    class _Resp:
        ok = True
        status_code = 200
        headers ={"Content-Type": "image/jpeg"}

        def iter_content(self, _n):
            yield b"x" * 50

        def close(self):
            pass

    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: _Resp())
    assert ci.fetch_and_store("https://cdn.example.com/big.jpg") is None
