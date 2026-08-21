import asyncio

import pytest

import engine.scraping.episodes as ep
import engine.scraping.parser as parser_mod
from engine.auth.manager import auth_manager
from engine.scraping.site.animessama import SITE_URL


class FakeResp:
    def __init__(self, text):
        self.text = text


class FakeDisk:
    def __init__(self):
        self.store = {}
        self.get_calls = []
        self.set_many_calls = []

    def get(self, key):
        self.get_calls.append(key)
        return self.store.get(key)

    def set(self, key, value):
        self.set_many_calls.append({key: value})
        self.store[key] = value

    def set_many(self, items):
        self.set_many_calls.append(dict(items))
        self.store.update(items)


class FakeCache:
    def __init__(self, lock_factory=None):
        self.mem = {}
        self.set_ep_calls = []
        self._lock_factory = lock_factory

    def get_ep(self, key):
        return self.mem.get(key)

    def set_ep(self, key, data):
        self.set_ep_calls.append((key, data))
        self.mem[key] = data

    def ep_lock(self, key):
        if self._lock_factory is None:
            return asyncio.Lock()
        return self._lock_factory(key)


@pytest.fixture(autouse=True)
def _restore_globals(monkeypatch):
    orig_disk = ep._ep_disk
    orig_cache = ep.cache
    orig_http = ep.http_get
    orig_safe = ep._is_safe_url
    orig_cookies = auth_manager.cookies
    orig_parse_saisons = parser_mod.parse_saisons
    orig_parse_episodes = parser_mod.parse_episodes
    yield
    ep._ep_disk = orig_disk
    ep.cache = orig_cache
    ep.http_get = orig_http
    ep._is_safe_url = orig_safe
    auth_manager.cookies = orig_cookies
    parser_mod.parse_saisons = orig_parse_saisons
    parser_mod.parse_episodes = orig_parse_episodes


def _install(monkeypatch, *, disk=None, cache=None, safe=True, cookies=None):
    disk = disk if disk is not None else FakeDisk()
    cache = cache if cache is not None else FakeCache()
    monkeypatch.setattr(ep, "_ep_disk", disk)
    monkeypatch.setattr(ep, "cache", cache)
    monkeypatch.setattr(ep, "_is_safe_url", lambda u: safe)
    monkeypatch.setattr(auth_manager, "cookies", cookies if cookies is not None else [])
    return disk, cache


def test_detecter_langue_vostfr():
    assert ep._detecter_langue("https://x/catalogue/naruto/saison1/vostfr") == "vostfr"


def test_detecter_langue_vf():
    assert ep._detecter_langue("https://x/catalogue/naruto/saison1/vf") == "vf"


def test_detecter_langue_trailing_slash_and_query():
    assert ep._detecter_langue("https://x/vf/") == "vf"
    assert ep._detecter_langue("https://x/saison1/va?p=1") == "va"


def test_detecter_langue_default_when_absent():
    assert ep._detecter_langue("https://x/catalogue/naruto") == "vostfr"
    assert ep._detecter_langue("") == "vostfr"
    assert ep._detecter_langue(None) == "vostfr"


def test_not_safe_url_returns_empty(monkeypatch):
    _install(monkeypatch, safe=False)
    out = asyncio.run(ep.get_episodes_async("ftp://evil/catalogue/x"))
    assert out == {"titre": "", "episodes": [], "langues": [], "total": 0}


def test_memory_cache_hit_short_circuits(monkeypatch):
    disk, cache = _install(monkeypatch)
    key = f"{SITE_URL}/catalogue/naruto"
    cache.mem[key] = {"titre": "T", "episodes": [{"n": 1}], "langues": ["vf"], "total": 1}

    def _boom(*a, **k):
        raise AssertionError("http_get must not be called on cache hit")

    monkeypatch.setattr(ep, "http_get", _boom)
    out = asyncio.run(ep.get_episodes_async(f"{SITE_URL}/catalogue/naruto"))
    assert out == cache.mem[key]
    assert disk.get_calls == []


def test_lock_none_returns_empty(monkeypatch):
    cache = FakeCache(lock_factory=lambda key: None)
    _install(monkeypatch, cache=cache)
    out = asyncio.run(ep.get_episodes_async(f"{SITE_URL}/catalogue/naruto"))
    assert out == {"titre": "", "episodes": [], "langues": [], "total": 0}


def test_disk_cache_hit_sets_mem_and_returns(monkeypatch):
    disk = FakeDisk()
    cache = FakeCache()
    _install(monkeypatch, disk=disk, cache=cache)
    key = f"{SITE_URL}/catalogue/naruto"
    cached = {"titre": "T", "episodes": [{"n": 1}], "langues": ["vf"], "total": 1}
    disk.store[key] = cached

    def _boom(*a, **k):
        raise AssertionError("http_get must not be called on disk hit")

    monkeypatch.setattr(ep, "http_get", _boom)
    out = asyncio.run(ep.get_episodes_async(f"{SITE_URL}/catalogue/naruto"))
    assert out == cached
    assert (key, cached) in cache.set_ep_calls


def test_happy_path_two_saisons_aggregates_and_caches(monkeypatch):
    disk, cache = _install(monkeypatch)

    async def _http_get(url, cookies):
        return FakeResp("<fiche>")

    monkeypatch.setattr(ep, "http_get", _http_get)

    parsed1 = {"titre": "Naruto", "episodes": [{"n": 1}, {"n": 2}], "langues": ["vf"]}
    parsed2 = {"titre": "Naruto", "episodes": [{"n": 3}], "langues": ["vostfr"]}
    saisons = [
        {"saison": 1, "url": f"{SITE_URL}/catalogue/naruto/saison1/vf", "_parsed": parsed1},
        {"saison": 2, "url": f"{SITE_URL}/catalogue/naruto/saison2/vf", "_parsed": parsed2},
    ]
    monkeypatch.setattr(parser_mod, "parse_saisons", lambda html: saisons)

    def _boom_pe(*a, **k):
        raise AssertionError("parse_episodes must not run when _parsed present")

    monkeypatch.setattr(parser_mod, "parse_episodes", _boom_pe)

    url = f"{SITE_URL}/catalogue/naruto/saison1/vf"
    out = asyncio.run(ep.get_episodes_async(url))

    assert out["titre"] == "Naruto"
    assert out["total"] == 3
    assert out["episodes"] == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert out["langues"] == ["vf", "vostfr"]

    cache_key = url
    fiche_key = f"{SITE_URL}/catalogue/naruto"
    assert (fiche_key, out) in cache.set_ep_calls
    assert (cache_key, out) in cache.set_ep_calls
    assert any(
        cache_key in d and fiche_key in d for d in disk.set_many_calls
    )


def test_single_saison_triggers_sondage(monkeypatch):
    disk, cache = _install(monkeypatch)

    season_pages = {
        f"{SITE_URL}/catalogue/naruto/saison1/vostfr": FakeResp("<s1>"),
        f"{SITE_URL}/catalogue/naruto/saison2/vostfr": FakeResp("<s2>"),
        f"{SITE_URL}/catalogue/naruto/saison3/vostfr": FakeResp("<s3>"),
    }

    async def _http_get(url, cookies):
        if url == f"{SITE_URL}/catalogue/naruto":
            return FakeResp("<fiche>")
        return season_pages.get(url)

    monkeypatch.setattr(ep, "http_get", _http_get)

    monkeypatch.setattr(
        parser_mod,
        "parse_saisons",
        lambda html: [{"saison": 1, "url": f"{SITE_URL}/catalogue/naruto/saison1/vostfr"}],
    )

    def _parse_episodes(text, url):
        if text == "<s1>":
            return {"titre": "Naruto", "episodes": [{"n": 1}], "langues": ["vostfr"]}
        if text == "<s2>":
            return {"titre": "Naruto", "episodes": [{"n": 2}], "langues": ["vostfr"]}
        return {"titre": "Naruto", "episodes": [], "langues": []}

    monkeypatch.setattr(parser_mod, "parse_episodes", _parse_episodes)
    monkeypatch.setattr(ep.time, "time", lambda: 1000.0)

    url = f"{SITE_URL}/catalogue/naruto/saison1/vostfr"
    out = asyncio.run(ep.get_episodes_async(url))

    assert out["total"] == 2
    assert out["episodes"] == [{"n": 1}, {"n": 2}]


def test_no_saison_with_saison_path_falls_back_to_fetch_saison(monkeypatch):
    disk, cache = _install(monkeypatch)

    url = f"{SITE_URL}/anime/naruto/saison1/vf"
    cache_key = url

    fetched = {"titre": "Naruto", "episodes": [{"n": 1}], "langues": ["vf"]}

    async def _http_get(u, cookies):
        if u == cache_key:
            return FakeResp("<saison-page>")
        return FakeResp("<fiche>")

    monkeypatch.setattr(ep, "http_get", _http_get)
    monkeypatch.setattr(parser_mod, "parse_saisons", lambda html: [])
    monkeypatch.setattr(
        parser_mod,
        "parse_episodes",
        lambda text, u: fetched if text == "<saison-page>" else {},
    )

    out = asyncio.run(ep.get_episodes_async(url))
    assert out == fetched
    assert (cache_key, fetched) in cache.set_ep_calls


def test_no_saison_without_saison_path_returns_empty(monkeypatch):
    disk, cache = _install(monkeypatch)

    async def _http_get(u, cookies):
        return FakeResp("<fiche>")

    monkeypatch.setattr(ep, "http_get", _http_get)
    monkeypatch.setattr(parser_mod, "parse_saisons", lambda html: [])

    def _boom_pe(*a, **k):
        raise AssertionError("parse_episodes should not run without /saisonN/ path")

    monkeypatch.setattr(parser_mod, "parse_episodes", _boom_pe)

    out = asyncio.run(ep.get_episodes_async(f"{SITE_URL}/catalogue/naruto"))
    assert out == {"titre": "", "episodes": [], "langues": [], "total": 0}


def test_fiche_unreachable_returns_empty(monkeypatch):
    disk, cache = _install(monkeypatch)

    async def _http_get(u, cookies):
        return None

    monkeypatch.setattr(ep, "http_get", _http_get)

    def _boom(*a, **k):
        raise AssertionError("parse_saisons should not run when fiche is None")

    monkeypatch.setattr(parser_mod, "parse_saisons", _boom)

    out = asyncio.run(ep.get_episodes_async(f"{SITE_URL}/catalogue/naruto"))
    assert out == {"titre": "", "episodes": [], "langues": [], "total": 0}
    assert cache.set_ep_calls == []


def test_timeout_path_returns_partial_and_not_cached(monkeypatch):
    disk, cache = _install(monkeypatch)

    async def _http_get(url, cookies):
        return FakeResp("<fiche>")

    monkeypatch.setattr(ep, "http_get", _http_get)

    saisons = [
        {"saison": 1, "url": f"{SITE_URL}/catalogue/naruto/saison1/vf", "_parsed": {"episodes": [{"n": 1}]}},
        {"saison": 2, "url": f"{SITE_URL}/catalogue/naruto/saison2/vf", "_parsed": {"episodes": [{"n": 2}]}},
    ]
    monkeypatch.setattr(parser_mod, "parse_saisons", lambda html: saisons)

    async def _fake_wait_for(coro, timeout):
        await coro
        raise TimeoutError

    monkeypatch.setattr(ep.asyncio, "wait_for", _fake_wait_for)

    url = f"{SITE_URL}/catalogue/naruto/saison1/vf"
    out = asyncio.run(ep.get_episodes_async(url))
    assert out["total"] == 2
    assert out["episodes"] == [{"n": 1}, {"n": 2}]
    assert cache.set_ep_calls == []
    assert disk.set_many_calls == []


def test_fetch_saison_returns_empty_when_no_response(monkeypatch):
    async def _http_get(url, cookies):
        return None

    monkeypatch.setattr(ep, "http_get", _http_get)

    def _boom(*a, **k):
        raise AssertionError("parse_episodes should not run when r is None")

    monkeypatch.setattr(parser_mod, "parse_episodes", _boom)

    out = asyncio.run(ep._fetch_saison(f"{SITE_URL}/catalogue/naruto/saison1/vf", []))
    assert out == {}


def test_fetch_saison_parses_when_response(monkeypatch):
    async def _http_get(url, cookies):
        return FakeResp("<page>")

    monkeypatch.setattr(ep, "http_get", _http_get)
    parsed = {"titre": "X", "episodes": [{"n": 1}], "langues": ["vf"]}
    monkeypatch.setattr(
        parser_mod,
        "parse_episodes",
        lambda text, url: parsed if text == "<page>" else {},
    )

    out = asyncio.run(ep._fetch_saison(f"{SITE_URL}/catalogue/naruto/saison1/vf", []))
    assert out == parsed


def test_lister_sondage_stops_after_consecutive_empties(monkeypatch):
    times = iter([1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0])
    monkeypatch.setattr(ep.time, "time", lambda: next(times))

    requested = []

    async def _http_get(url, cookies):
        requested.append(url)
        return FakeResp(url)

    monkeypatch.setattr(ep, "http_get", _http_get)

    def _parse_episodes(text, url):
        if "saison1" in url:
            return {"episodes": [{"n": 1}]}
        return {"episodes": []}

    monkeypatch.setattr(parser_mod, "parse_episodes", _parse_episodes)

    out = asyncio.run(ep._lister_saisons_par_sondage([], "naruto", "vostfr", saison_max_connu=1))

    assert len(out) == 1
    assert out[0]["saison"] == 1
    assert requested == [
        f"{SITE_URL}/catalogue/naruto/saison1/vostfr",
        f"{SITE_URL}/catalogue/naruto/saison2/vostfr",
        f"{SITE_URL}/catalogue/naruto/saison2/vostfr/episodes.js",
        f"{SITE_URL}/catalogue/naruto/saison3/vostfr",
        f"{SITE_URL}/catalogue/naruto/saison3/vostfr/episodes.js",
    ]


def test_lister_sondage_respects_deadline(monkeypatch):
    times = iter([1000.0, 9999.0])
    monkeypatch.setattr(ep.time, "time", lambda: next(times))

    called = []

    async def _http_get(url, cookies):
        called.append(url)
        return FakeResp(url)

    monkeypatch.setattr(ep, "http_get", _http_get)
    monkeypatch.setattr(parser_mod, "parse_episodes", lambda text, url: {"episodes": [{"n": 1}]})

    out = asyncio.run(ep._lister_saisons_par_sondage([], "naruto", "vostfr"))
    assert out == []
    assert called == []
