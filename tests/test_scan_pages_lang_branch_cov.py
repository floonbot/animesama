"""Regression: get_pages_sync ignored its lang parameter (dead), unlike its
sibling get_scan_info_sync which passes lang to the same endpoint. The lang is
now forwarded so a va scan is not counted with vf page counts.
"""

import json

import engine.scraping.scan as scan_mod


def test_get_pages_sync_forwards_lang(monkeypatch):
    seen = {}

    def fake_retry(url, referer=None):
        seen["url"] = url
        return json.dumps({"1": 2})

    monkeypatch.setattr(scan_mod, "_fetch_api_retry", fake_retry)
    out = scan_mod.get_pages_sync("Work", "1", "va")

    assert "lang=va" in seen["url"]
    assert [p["page"] for p in out] == [1, 2]
