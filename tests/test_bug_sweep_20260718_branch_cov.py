import asyncio
import sqlite3

import pytest

import engine.scraping.search as search_mod
from engine.download.store import DownloadStore


class _TruthyResp:
    def __init__(self, text="", ok=True):
        self.text = text
        self._ok = ok

    def __bool__(self):
        return self._ok


def _fake_auth(monkeypatch):
    import engine.auth.manager as auth_mod

    class _AM:
        pass

    am = _AM()
    am.cookies = []
    monkeypatch.setattr(auth_mod, "auth_manager", am)


@pytest.fixture
def _restore_types_cache():
    saved_cache = dict(search_mod._types_cache)
    saved_loaded = search_mod._types_loaded
    try:
        yield
    finally:
        search_mod._types_cache.clear()
        search_mod._types_cache.update(saved_cache)
        search_mod._types_loaded = saved_loaded


def test_detecter_types_unrecognized_page_not_cached_as_scan(monkeypatch, _restore_types_cache):
    _fake_auth(monkeypatch)
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    search_mod._types_cache.clear()
    monkeypatch.setattr(search_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(search_mod, "_save_types_cache", lambda: None)

    url = "https://anime-sama.to/catalogue/foo"

    async def _get(u, cookies):
        return _TruthyResp(text="", ok=True)

    monkeypatch.setattr(search_mod, "http_get", _get)
    monkeypatch.setattr(
        "engine.scraping.parser.detecter_type_contenu",
        lambda html: {"has_scan": False, "has_anime": False},
    )

    res = asyncio.run(search_mod.detecter_types_favoris_async([url]))

    assert res == {}
    assert url not in search_mod._types_cache


def test_detecter_types_real_scan_still_classified(monkeypatch, _restore_types_cache):
    _fake_auth(monkeypatch)
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    search_mod._types_cache.clear()
    monkeypatch.setattr(search_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(search_mod, "_save_types_cache", lambda: None)

    url = "https://anime-sama.to/catalogue/bar"

    async def _get(u, cookies):
        return _TruthyResp(text="page", ok=True)

    monkeypatch.setattr(search_mod, "http_get", _get)
    monkeypatch.setattr(
        "engine.scraping.parser.detecter_type_contenu",
        lambda html: {"has_scan": True, "has_anime": False},
    )

    res = asyncio.run(search_mod.detecter_types_favoris_async([url]))

    assert res == {url: "scan"}
    assert search_mod._types_cache[url] == "scan"


def test_store_write_error_rollback_runs_under_lock(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    real = s._conn
    observed: dict = {}

    class _FailCommitConn:
        def execute(self, *a, **k):
            return real.execute(*a, **k)

        def executemany(self, *a, **k):
            return real.executemany(*a, **k)

        def commit(self):
            raise sqlite3.OperationalError("boom")

        def rollback(self):
            observed["locked_during_rollback"] = s._lock.locked()
            return real.rollback()

        def close(self):
            return real.close()

    try:
        s._conn = _FailCommitConn()
        s._save_current_sync('{"nom": "x"}')
        assert observed.get("locked_during_rollback") is True
    finally:
        s._conn = real
        s.close()
