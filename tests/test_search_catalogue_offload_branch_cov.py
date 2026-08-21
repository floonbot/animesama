import asyncio
import threading

import engine.scraping.catalogue as cat_mod
import engine.scraping.search as search_mod


class FakeResp:
    def __init__(self, text="", ok=True):
        self.text = text
        self._ok = ok

    def __bool__(self):
        return self._ok


def _fake_auth(monkeypatch):
    import engine.auth.manager as auth_mod

    class _AM:
        cookies: list = []

    monkeypatch.setattr(auth_mod, "auth_manager", _AM())


def test_search_async_parse_deporte_hors_loop(monkeypatch):
    _fake_auth(monkeypatch)
    loop_thread = threading.get_ident()
    seen = {}

    async def _post(url, cookies, data):
        return FakeResp(text="x")

    def _parse(html):
        seen["thread"] = threading.get_ident()
        return []

    monkeypatch.setattr(search_mod, "http_post", _post)
    monkeypatch.setattr("engine.scraping.parser.parse_search_results", _parse)

    asyncio.run(search_mod.search_async("naruto"))

    assert seen["thread"] != loop_thread


def test_catalogue_async_parse_deporte_hors_loop(monkeypatch):
    _fake_auth(monkeypatch)
    loop_thread = threading.get_ident()
    seen = {}

    async def _get(url, cookies):
        return FakeResp(text="x")

    def _parse(html):
        seen["thread"] = threading.get_ident()
        return []

    monkeypatch.setattr(cat_mod, "http_get", _get)
    monkeypatch.setattr("engine.scraping.parser.parse_search_results", _parse)

    asyncio.run(cat_mod.catalogue_async(genre="Action"))

    assert seen["thread"] != loop_thread
