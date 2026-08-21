import json

import pytest

from engine.scraping import scan as scan_mod


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
    """Isolate the in-memory cache, miss-only disk cache and sleep per test."""
    with scan_mod._scan_info_lock:
        snapshot = dict(scan_mod._scan_info_cache)
        scan_mod._scan_info_cache.clear()
    monkeypatch.setattr(scan_mod, "_scan_disk", _FakeDisk())
    monkeypatch.setattr(scan_mod.time, "sleep", lambda _s: None)
    yield
    with scan_mod._scan_info_lock:
        scan_mod._scan_info_cache.clear()
        scan_mod._scan_info_cache.update(snapshot)


def _page_html(title="My Work"):
    return (
        "<html><body>"
        f'<h3 id="titreOeuvre">{title}</h3>'
        '<select id="selectChapitres"><option>Chapitre 1</option></select>'
        "</body></html>"
    )


def test_happy_path_sorts_coerces_caches(monkeypatch):
    """A full success builds a numerically sorted, int-coerced result cached in memory and disk."""
    chapters = {"3": "10", "1": "20", "2": "15", "10": "5"}
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (200, _page_html()))
    monkeypatch.setattr(
        scan_mod, "_fetch_api_retry", lambda *a, **k: json.dumps(chapters)
    )

    out = scan_mod.get_scan_info_sync("my-work", "vf")

    assert out["ok"] is True
    assert out["slug"] == "my-work"
    assert out["oeuvre"] == "My Work"
    assert out["lang"] == "vf"
    assert out["langues"] == ["vf"]
    assert out["total"] == 4
    assert [c["num"] for c in out["chapitres"]] == ["1", "2", "3", "10"]
    assert [c["pages"] for c in out["chapitres"]] == [20, 15, 10, 5]
    assert all(isinstance(c["pages"], int) for c in out["chapitres"])

    assert scan_mod._scan_disk.set_calls == [("my-work|vf", out)]
    assert scan_mod._scan_info_get("my-work|vf") is out


def test_second_call_served_from_memory_cache(monkeypatch):
    """After a success, a second call returns the cached dict without touching fetchers."""
    chapters = {"1": "20"}
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (200, _page_html()))
    monkeypatch.setattr(
        scan_mod, "_fetch_api_retry", lambda *a, **k: json.dumps(chapters)
    )

    first = scan_mod.get_scan_info_sync("my-work", "vf")

    def _boom_text(*a, **k):
        raise AssertionError("_fetch_text must not run on a memory cache hit")

    def _boom_api(*a, **k):
        raise AssertionError("_fetch_api_retry must not run on a memory cache hit")

    monkeypatch.setattr(scan_mod, "_fetch_text", _boom_text)
    monkeypatch.setattr(scan_mod, "_fetch_api_retry", _boom_api)

    second = scan_mod.get_scan_info_sync("my-work", "vf")

    assert second is first
    assert second["ok"] is True


def test_non_numeric_pages_coerced_to_zero(monkeypatch):
    """A non-numeric pages value falls into the int() ValueError branch and becomes 0."""
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (200, _page_html()))
    monkeypatch.setattr(
        scan_mod, "_fetch_api_retry", lambda *a, **k: json.dumps({"1": "abc"})
    )

    out = scan_mod.get_scan_info_sync("my-work", "vf")

    assert out["ok"] is True
    assert out["chapitres"] == [{"num": "1", "pages": 0}]


def test_max_chapitres_cap_truncates_at_5000(monkeypatch):
    """A payload of 5001 chapters is truncated to _MAX_CHAPITRES by the break."""
    assert scan_mod._MAX_CHAPITRES == 5000
    chapters = {str(i): 1 for i in range(5001)}
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (200, _page_html()))
    monkeypatch.setattr(
        scan_mod, "_fetch_api_retry", lambda *a, **k: json.dumps(chapters)
    )

    out = scan_mod.get_scan_info_sync("my-work", "vf")

    assert out["ok"] is True
    assert len(out["chapitres"]) == 5000
    assert out["total"] == 5000


def test_float_and_non_numeric_key_ordering(monkeypatch):
    """Keys order by _chap_sort_key float value; a non-numeric key floats to inf and sorts last."""
    chapters = {"5": "1", "1.5": "2", "2": "3", "bonus": "4"}
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (200, _page_html()))
    monkeypatch.setattr(
        scan_mod, "_fetch_api_retry", lambda *a, **k: json.dumps(chapters)
    )

    out = scan_mod.get_scan_info_sync("my-work", "vf")

    assert out["ok"] is True
    assert [c["num"] for c in out["chapitres"]] == ["1.5", "2", "5", "bonus"]
    assert scan_mod._chap_sort_key("bonus") == float("inf")
    assert scan_mod._chap_sort_key("1.5") < scan_mod._chap_sort_key("2")


def test_va_language_threaded_through_result(monkeypatch):
    """A normalisable 'va' language is reflected in lang/langues and the cache key."""
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (200, _page_html()))
    monkeypatch.setattr(
        scan_mod, "_fetch_api_retry", lambda *a, **k: json.dumps({"1": "7"})
    )

    out = scan_mod.get_scan_info_sync("my-work", "va")

    assert out["lang"] == "va"
    assert out["langues"] == ["va"]
    assert scan_mod._scan_disk.set_calls == [("my-work|va", out)]
