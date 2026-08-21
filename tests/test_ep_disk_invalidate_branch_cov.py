"""Regression: invalidate_ep_cache purged only the in-memory episode cache; the
DiskCache("episodes", 3600) kept serving stale data for up to an hour. A disk
delete now mirrors the in-memory key derivation (episode URL + fiche slug key).

Order-safe: the module DiskCache file/state is snapshotted and restored.
"""

import asyncio

import pytest

import engine.scraping.episodes as episodes_mod
from engine.scraping.site.animessama import SITE_URL


@pytest.fixture(autouse=True)
def _restore_ep_disk():
    disk = episodes_mod._ep_disk
    with disk._lock:
        conn = disk._connexion()
        snap = conn.execute("SELECT key, ts, payload FROM cache").fetchall() if conn else []
    yield
    with disk._lock:
        conn = disk._connexion()
        if conn is not None:
            conn.execute("DELETE FROM cache")
            conn.executemany(
                "INSERT INTO cache (key, ts, payload) VALUES (?, ?, ?)", snap
            )
            conn.commit()


def test_invalidate_ep_disk_deletes_url_and_fiche_keys():
    disk = episodes_mod._ep_disk
    url = f"{SITE_URL}/catalogue/zzz-test-oeuvre/saison1/vostfr"
    fiche_key = f"{SITE_URL}/catalogue/zzz-test-oeuvre"

    disk.set(url, {"episodes": [1]})
    disk.set(fiche_key, {"episodes": [1, 2]})
    assert disk.get(url) == {"episodes": [1]}
    assert disk.get(fiche_key) == {"episodes": [1, 2]}

    episodes_mod.invalidate_ep_disk(url + "?ep=3")

    assert disk.get(url) is None
    assert disk.get(fiche_key) is None


def test_invalidate_ep_cache_awaits_disk_purge(monkeypatch):
    calls = {}

    def _fake(url=None):
        calls["url"] = url

    monkeypatch.setattr(episodes_mod, "invalidate_ep_disk", _fake)
    from engine.scraping import scraper as scraper_mod

    asyncio.run(scraper_mod.invalidate_ep_cache("http://x/catalogue/a/saison1?ep=1"))
    assert calls["url"] == "http://x/catalogue/a/saison1?ep=1"
