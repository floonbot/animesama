import json

from engine.scraping import scan as scan_mod


def test_get_pages_sync_caps_page_count(monkeypatch):
    def fake_fetch(url, referer=None, max_bytes=0):
        return 200, json.dumps({"7": 999999999})

    monkeypatch.setattr(scan_mod, "_fetch_text", fake_fetch)
    out = scan_mod.get_pages_sync("Oeuvre", "7", "vf")

    assert len(out) == scan_mod._MAX_PAGES
    assert out[0]["page"] == 1
    assert out[-1]["page"] == scan_mod._MAX_PAGES


def test_get_pages_sync_small_count_unaffected(monkeypatch):
    def fake_fetch(url, referer=None, max_bytes=0):
        return 200, json.dumps({"7": 3})

    monkeypatch.setattr(scan_mod, "_fetch_text", fake_fetch)
    out = scan_mod.get_pages_sync("Oeuvre", "7", "vf")

    assert [p["page"] for p in out] == [1, 2, 3]
