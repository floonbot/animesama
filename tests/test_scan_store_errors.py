import json

import pytest

from engine.download.store import DownloadStore
from engine.scraping import scan as scan_mod


class _FakeStreamResp:
    """Streaming response with a settable encoding and scripted chunks."""

    def __init__(self, status_code=200, chunks=None, encoding="utf-8"):
        self.status_code = status_code
        self.encoding = encoding
        self._chunks = chunks if chunks is not None else []
        self.closed = 0

    def iter_content(self, _size):
        yield from self._chunks

    def close(self):
        self.closed += 1


class _FakeSession:
    """Session whose get returns a scripted response."""

    def __init__(self, response):
        self._response = response
        self.get_calls = 0

    def get(self, url, headers=None, timeout=None, stream=None):
        self.get_calls += 1
        return self._response


class _FakeDisk:
    """Disk cache that always misses and records set calls."""

    def __init__(self):
        self.get_calls = []
        self.set_calls = []

    def get(self, key):
        self.get_calls.append(key)
        return None

    def set(self, key, value):
        self.set_calls.append((key, value))


@pytest.fixture(autouse=True)
def _reset_scan_state(monkeypatch):
    """Isolate the in-memory cache, disk cache and sleep for every test."""
    with scan_mod._scan_info_lock:
        snapshot = dict(scan_mod._scan_info_cache)
        scan_mod._scan_info_cache.clear()
    monkeypatch.setattr(scan_mod, "_scan_disk", _FakeDisk())
    monkeypatch.setattr(scan_mod.time, "sleep", lambda _s: None)
    yield
    with scan_mod._scan_info_lock:
        scan_mod._scan_info_cache.clear()
        scan_mod._scan_info_cache.update(snapshot)


def test_fetch_text_invalid_encoding_falls_back_to_utf8(monkeypatch):
    """An undecodable .encoding triggers the LookupError branch and utf-8 decode."""
    payload = "café ☃".encode()
    resp = _FakeStreamResp(status_code=200, chunks=[payload], encoding="invalid-codec-xyz")
    session = _FakeSession(resp)
    monkeypatch.setattr(scan_mod, "_get_session", lambda _heads: session)

    status, text = scan_mod._fetch_text("http://x/y")

    assert status == 200
    assert text == payload.decode("utf-8", errors="replace")
    assert resp.closed == 1


def test_fetch_text_concatenates_streamed_chunks_tolerating_empties(monkeypatch):
    """Streamed chunks are concatenated and decoded; interspersed empty chunks are tolerated."""
    resp = _FakeStreamResp(status_code=200, chunks=[b"", b"ab", b"", b"cd", b""])
    session = _FakeSession(resp)
    monkeypatch.setattr(scan_mod, "_get_session", lambda _heads: session)

    status, text = scan_mod._fetch_text("http://x/y")

    assert status == 200
    assert text == "abcd"


_PAGE_HTML = (
    '<html><body>'
    '<h3 id="titreOeuvre">My Work</h3>'
    '<select id="selectChapitres"><option>Chapitre 1</option></select>'
    '</body></html>'
)


def test_get_scan_info_sync_api_unreachable(monkeypatch):
    """A None body from _fetch_api_retry yields the 'API chapitres injoignable' shape."""
    monkeypatch.setattr(
        scan_mod, "_fetch_text", lambda *a, **k: (200, _PAGE_HTML)
    )
    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda *a, **k: None)

    out = scan_mod.get_scan_info_sync("good-slug", "vf")

    assert out == {
        "ok": False,
        "error": "API chapitres injoignable",
        "chapitres": [],
        "langues": ["vf"],
        "oeuvre": "My Work",
        "lang": "vf",
    }


def test_get_scan_info_sync_unreadable_json(monkeypatch):
    """A non-JSON API body yields the 'réponse chapitres illisible' shape."""
    monkeypatch.setattr(
        scan_mod, "_fetch_text", lambda *a, **k: (200, _PAGE_HTML)
    )
    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda *a, **k: "not json {{{")

    out = scan_mod.get_scan_info_sync("good-slug", "vf")

    assert out == {
        "ok": False,
        "error": "réponse chapitres illisible",
        "chapitres": [],
        "langues": ["vf"],
        "oeuvre": "My Work",
        "lang": "vf",
    }


def test_get_scan_info_sync_title_missing(monkeypatch):
    """selectChapitres present but no titreOeuvre yields the 'titre introuvable' shape."""
    html = '<html><select id="selectChapitres"></select></html>'
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (200, html))

    def _boom(*a, **k):
        raise AssertionError("API must not be queried without a title")

    monkeypatch.setattr(scan_mod, "_fetch_api_retry", _boom)

    out = scan_mod.get_scan_info_sync("good-slug", "vf")

    assert out == {
        "ok": False,
        "error": "titre d'œuvre introuvable",
        "chapitres": [],
        "langues": ["vf"],
    }


def test_get_scan_info_sync_unreadable_does_not_cache(monkeypatch):
    """Error results are never written to memory or disk cache."""
    fake_disk = _FakeDisk()
    monkeypatch.setattr(scan_mod, "_scan_disk", fake_disk)
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (200, _PAGE_HTML))
    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda *a, **k: None)

    scan_mod.get_scan_info_sync("good-slug", "vf")

    assert fake_disk.set_calls == []
    assert scan_mod._scan_info_get("good-slug|vf") is None


def test_get_pages_sync_api_unreachable_returns_empty(monkeypatch):
    """A None body from the pages API yields an empty list."""
    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda *a, **k: None)

    assert scan_mod.get_pages_sync("Work", "1", "vf") == []


def test_get_pages_sync_bad_json_returns_empty(monkeypatch):
    """An unparseable pages body yields an empty list."""
    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda *a, **k: "}{ not json")

    assert scan_mod.get_pages_sync("Work", "1", "vf") == []


def test_get_pages_sync_non_list_payload_returns_empty(monkeypatch):
    """A valid-JSON scalar (not a list) is rejected by the isinstance(list) guard, returning []."""
    monkeypatch.setattr(
        scan_mod, "_fetch_api_retry", lambda *a, **k: json.dumps(5)
    )

    assert scan_mod.get_pages_sync("Work", "1", "vf") == []


def test_load_queue_after_close_returns_empty(tmp_path):
    """Reading the queue after close hits sqlite3.Error and returns []."""
    s = DownloadStore(tmp_path / "d.db")
    s.save_queue([{"a": 1}])
    s.load_queue()
    s.close()

    assert s.load_queue() == []


def test_load_history_after_close_returns_empty(tmp_path):
    """Reading history after close hits sqlite3.Error and returns []."""
    s = DownloadStore(tmp_path / "d.db")
    s.append_history({"i": 0})
    s.load_history()
    s.close()

    assert s.load_history() == []


def test_load_current_after_close_returns_none(tmp_path):
    """Reading the current item after close hits sqlite3.Error and returns None."""
    s = DownloadStore(tmp_path / "d.db")
    s.save_current({"nom": "A"})
    s.load_current()
    s.close()

    assert s.load_current() is None


def test_save_queue_skips_non_serialisable_set_entry(tmp_path):
    """A queue entry containing a set is dropped via the json.dumps TypeError guard."""
    s = DownloadStore(tmp_path / "d.db")
    try:
        s.save_queue([{"ok": 1}, {"x": {1, 2}}, {"ok": 2}])
        assert s.load_queue() == [{"ok": 1}, {"ok": 2}]
    finally:
        s.close()


def test_append_history_skips_non_serialisable_entry(tmp_path):
    """A history entry with a set value is silently skipped before any write."""
    s = DownloadStore(tmp_path / "d.db")
    try:
        s.append_history({"bad": {1, 2}})
        s.append_history({"good": 1})
        assert s.load_history() == [{"good": 1}]
    finally:
        s.close()


def test_save_current_skips_non_serialisable_entry(tmp_path):
    """A non-serialisable current item is skipped and leaves no row behind."""
    s = DownloadStore(tmp_path / "d.db")
    try:
        s.save_current({"bad": {1, 2}})
        assert s.load_current() is None
    finally:
        s.close()
