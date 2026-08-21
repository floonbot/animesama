"""Deterministic coverage-gap tests for the parsing cluster.

Targets named line/branch gaps in engine.scraping.parser._base, players,
episodes, scan, search, parser.profile, parser.search, _cache and
http_client that the existing suite leaves open. Every fixture is an inline
string or a stub object; the only async surfaces monkeypatch the module-level
http_get / asyncio client so no network, socket, subprocess, browser or
wall-clock is involved. Module singletons that are mutated (the _base.json
reference, http_client session caches, search._TYPES_FILE / _types_cache /
_types_loaded, episodes.cache / _ep_disk / http_get / _is_safe_url and the
auth_manager cookies) are snapshotted and restored so the tests stay
independent of pytest-randomly ordering.
"""

import asyncio
import json
import types

import pytest

import engine.scraping._cache as cache_mod
import engine.scraping.episodes as ep
import engine.scraping.http_client as hc
import engine.scraping.parser as parser_mod
import engine.scraping.parser._base as base
import engine.scraping.scan as scan_mod
import engine.scraping.search as search_mod
from engine.auth.manager import auth_manager
from engine.scraping.parser._base import _attr_str, _extraire_eps_arrays, _extraire_tableau_js
from engine.scraping.parser.search import parse_search_results
from engine.scraping.site.animessama import SITE_URL


@pytest.fixture(autouse=True)
def _clear_season_cache():
    import engine.scraping.players as players_mod
    players_mod.clear_season_cache()
    yield
    players_mod.clear_season_cache()


class _GetStub:
    """Minimal Tag-like exposing get() so _attr_str sees an arbitrary value."""

    def __init__(self, value) -> None:
        self._value = value

    def get(self, name, default=""):
        return self._value


def test_attr_str_list_value_is_space_joined():
    """_base.py:40 — a list attribute value is space-joined into a single string."""
    assert _attr_str(_GetStub(["a", "b", 3]), "class", "fallback") == "a b 3"


def test_attr_str_non_str_non_list_value_returns_default():
    """_base.py:41 — a value that is neither list nor str falls back to the default."""
    assert _attr_str(_GetStub(123), "href", "fallback") == "fallback"


def test_extraire_tableau_js_nested_brackets_keep_depth_positive():
    """_base.py:118->101 — a nested ']' leaves depth>0 and the loop continues."""
    assert _extraire_tableau_js("v = [[1],[2]]", 4) == "[[1],[2]]"


def test_extraire_eps_arrays_non_list_payload_is_skipped(monkeypatch):
    """_base.py:177->164 — a parsed payload that is not a list is dropped and the loop continues."""
    fake_json = types.SimpleNamespace(
        loads=lambda raw: {"not": "a list"},
        JSONDecodeError=json.JSONDecodeError,
    )
    monkeypatch.setattr(base, "json", fake_json)
    assert _extraire_eps_arrays('var eps1 = ["x"]') == {}


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


def test_get_lecteurs_async_absolute_url_not_prefixed(monkeypatch):
    """players.py:17->20 — an already-absolute url skips the SITE_URL prefix step."""
    recorded: dict = {}

    async def fake_http_get(url, cookies):
        recorded["url"] = url
        return _FakeResp('var eps1=["https://a.tld/1"]')

    import engine.scraping.players as players_mod

    saved_cookies = auth_manager.cookies
    monkeypatch.setattr(players_mod, "http_get", fake_http_get)
    monkeypatch.setattr(auth_manager, "cookies", [])
    absolute = f"{SITE_URL}/catalogue/x/saison1/vostfr?ep=1"
    try:
        result = asyncio.run(players_mod.get_lecteurs_async(absolute))
    finally:
        auth_manager.cookies = saved_cookies

    assert recorded["url"] == f"{SITE_URL}/catalogue/x/saison1/vostfr"
    assert result == [{"host": "a.tld", "src": "https://a.tld/1"}]


def test_parse_search_results_img_with_blank_alt_falls_back_to_slug():
    """parser/search.py:47->49 — an <img> with an unusable alt leaves nom empty and the slug is used."""
    results = parse_search_results('<a href="/catalogue/naruto"><img alt=""></a>')
    assert results[0]["nom"] == "Naruto"


class _EpResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _EpFakeDisk:
    def __init__(self) -> None:
        self.store: dict = {}
        self.set_many_calls: list = []

    def get(self, key):
        return self.store.get(key)

    def set_many(self, items):
        self.set_many_calls.append(dict(items))
        self.store.update(items)


class _EpFakeCache:
    def __init__(self) -> None:
        self.mem: dict = {}
        self.set_ep_calls: list = []

    def get_ep(self, key):
        return self.mem.get(key)

    def set_ep(self, key, data):
        self.set_ep_calls.append((key, data))
        self.mem[key] = data

    def ep_lock(self, key):
        return asyncio.Lock()


@pytest.fixture
def ep_env(monkeypatch):
    """Wires episodes.py onto in-memory fakes and restores the singletons afterwards."""
    saved = (ep._ep_disk, ep.cache, ep.http_get, ep._is_safe_url, auth_manager.cookies)
    disk = _EpFakeDisk()
    fcache = _EpFakeCache()
    monkeypatch.setattr(ep, "_ep_disk", disk)
    monkeypatch.setattr(ep, "cache", fcache)
    monkeypatch.setattr(ep, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(auth_manager, "cookies", [])
    yield disk, fcache, monkeypatch
    ep._ep_disk, ep.cache, ep.http_get, ep._is_safe_url, auth_manager.cookies = saved


def test_get_episodes_force_refresh_skips_caches_and_fiche_disk(ep_env):
    """episodes.py:72->78, 84->94, 108->114 — force_refresh bypasses mem/disk lookups."""
    disk, fcache, mp = ep_env
    url = f"{SITE_URL}/catalogue/naruto/saison1/vf"
    cache_key = url
    fiche_key = f"{SITE_URL}/catalogue/naruto"
    poisoned = {"titre": "STALE", "episodes": [{"n": 9}], "langues": ["vf"], "total": 1}
    fcache.mem[cache_key] = poisoned
    disk.store[cache_key] = poisoned
    disk.store[fiche_key] = poisoned

    async def _http_get(u, cookies):
        return _EpResp("<fiche>")

    mp.setattr(ep, "http_get", _http_get)
    fresh = {"titre": "Naruto", "episodes": [{"n": 1}], "langues": ["vf"]}
    saisons = [{"saison": 1, "url": cache_key, "_parsed": fresh}]
    mp.setattr(parser_mod, "parse_saisons", lambda html: saisons)

    out = asyncio.run(ep.get_episodes_async(url, force_refresh=True))

    assert out["titre"] == "Naruto"
    assert out["total"] == 1
    assert out["episodes"] == [{"n": 1}]


def test_get_episodes_fetch_saison_without_episodes_returns_uncached(ep_env):
    """episodes.py:140->143 — the saison-fallback result lacking episodes is returned, not cached."""
    disk, fcache, mp = ep_env
    url = f"{SITE_URL}/catalogue/x/saison1/vf"

    async def _http_get(u, cookies):
        return _EpResp("<page>")

    mp.setattr(ep, "http_get", _http_get)
    mp.setattr(parser_mod, "parse_saisons", lambda html: [])
    mp.setattr(parser_mod, "parse_episodes", lambda text, u: {"titre": "Sans eps"})

    out = asyncio.run(ep.get_episodes_async(url))

    assert out == {"titre": "Sans eps"}
    assert fcache.set_ep_calls == []
    assert disk.set_many_calls == []


def test_get_episodes_non_catalogue_url_caches_single_key(ep_env):
    """episodes.py:204->206, 207->209 — when fiche_key == cache_key only one key is written."""
    disk, fcache, mp = ep_env
    url = f"{SITE_URL}/anime/onepiece"

    async def _http_get(u, cookies):
        return _EpResp("<fiche>")

    mp.setattr(ep, "http_get", _http_get)
    parsed = {"titre": "One Piece", "episodes": [{"n": 1}], "langues": ["vf"]}
    saisons = [{"saison": 1, "url": url, "_parsed": parsed}]
    mp.setattr(parser_mod, "parse_saisons", lambda html: saisons)

    out = asyncio.run(ep.get_episodes_async(url))

    assert out["titre"] == "One Piece"
    assert out["total"] == 1
    assert [k for k, _ in fcache.set_ep_calls] == [url]
    assert disk.set_many_calls == [{url: out}]


def test_get_scan_info_non_dict_chapitres_payload_yields_empty(monkeypatch):
    """scan.py:154->166 — a non-dict chapter payload skips the loop and reports zero chapters."""
    saved = dict(scan_mod._scan_info_cache)

    class _NoDisk:
        def get(self, key):
            return None

        def set(self, key, value):
            pass

    monkeypatch.setattr(scan_mod, "_scan_disk", _NoDisk())
    monkeypatch.setattr(scan_mod, "_extraire_oeuvre", lambda html: "Mon Oeuvre")
    monkeypatch.setattr(
        scan_mod, "_fetch_text", lambda *a, **k: (200, "x selectChapitres y")
    )
    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda *a, **k: "[1, 2, 3]")
    scan_mod._scan_info_cache.clear()
    try:
        out = scan_mod.get_scan_info_sync("naruto", "vf")
    finally:
        scan_mod._scan_info_cache.clear()
        scan_mod._scan_info_cache.update(saved)

    # `ok: True` avec zero chapitre etait un mensonge poli : la modale s'ouvrait
    # sur une liste vide au lieu de dire ce qui manquait. Une charge utile qui
    # n'est pas un objet de chapitres est un echec, et le porte.
    assert out["ok"] is False
    assert out["chapitres"] == []
    assert out["error"]


@pytest.fixture
def types_file(tmp_path, monkeypatch):
    """Redirects search._TYPES_FILE to tmp_path and restores the cache singletons."""
    saved_cache = dict(search_mod._types_cache)
    saved_loaded = search_mod._types_loaded
    saved_file = search_mod._TYPES_FILE
    target = tmp_path / "scan_types.json"
    monkeypatch.setattr(search_mod, "_TYPES_FILE", target)
    monkeypatch.setattr(search_mod, "_types_loaded", False)
    search_mod._types_cache.clear()
    yield target
    search_mod._types_cache.clear()
    search_mod._types_cache.update(saved_cache)
    search_mod._types_loaded = saved_loaded
    search_mod._TYPES_FILE = saved_file


def test_load_types_cache_missing_file_is_noop(types_file):
    """search.py:37->exit — an absent types file leaves the cache empty."""
    assert not types_file.exists()
    search_mod._load_types_cache()
    assert search_mod._types_cache == {}
    assert search_mod._types_loaded is True


def test_load_types_cache_non_dict_payload_ignored(types_file):
    """search.py:40->exit — a non-dict JSON payload is ignored without populating the cache."""
    types_file.write_text("[1, 2, 3]", encoding="utf-8")
    search_mod._load_types_cache()
    assert search_mod._types_cache == {}


def test_load_types_cache_skips_invalid_type_values(types_file):
    """search.py:42->41 — entries whose value is not a known type are skipped."""
    types_file.write_text(
        json.dumps({"u1": "scan", "u2": "garbage", "u3": "anime"}), encoding="utf-8"
    )
    search_mod._load_types_cache()
    assert search_mod._types_cache == {"u1": "scan", "u3": "anime"}


def test_set_ep_purge_frees_room_skips_lru_drop():
    """_cache.py:90->93 — when purge frees enough room, the LRU-drop block is skipped."""
    c = cache_mod.ScraperCache()
    stale_ts = 0.0
    for i in range(cache_mod.EP_CACHE_MAX):
        c._ep[f"k{i}"] = ({"i": i}, stale_ts)
    assert len(c._ep) == cache_mod.EP_CACHE_MAX
    c.set_ep("fresh", {"i": -1})
    assert c.get_ep("fresh") == {"i": -1}
    assert all(k == "fresh" for k in c._ep)


@pytest.fixture
def hc_state():
    """Snapshots and restores the http_client session-cache singletons."""
    saved_cache = dict(hc._session_cache)
    saved_order = list(hc._session_keys_order)
    yield
    hc._session_cache.clear()
    hc._session_cache.update(saved_cache)
    hc._session_keys_order[:] = saved_order


class _HcFakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_get_session_eviction_skips_missing_key(monkeypatch, hc_state):
    """http_client.py:105->102 — a stale order key absent from the cache evicts nothing and the loop continues."""
    monkeypatch.setattr(hc, "SESSION_CACHE_MAX", 1)
    real = _HcFakeSession()
    hc._session_cache.clear()
    hc._session_keys_order.clear()
    hc._session_cache["real"] = real
    hc._session_keys_order[:] = ["stale", "real"]
    built = _HcFakeSession()
    monkeypatch.setattr(hc, "_build_session", lambda cookies: built)

    out = hc._get_session([{"name": "n", "value": "v"}])

    assert out is built
    assert real.closed is True
    assert "real" not in hc._session_cache


class _HcCLResponse:
    def __init__(self, content_length: str, chunks) -> None:
        self.status_code = 200
        self.ok = True
        self.headers = {"Content-Length": content_length}
        self._chunks = list(chunks)
        self.encoding = None
        self.closed = False
        self._content = None
        self._content_consumed = False

    def iter_content(self, size):
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


class _HcSession:
    def __init__(self, resp) -> None:
        self._resp = resp
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self._resp


def test_http_get_content_length_within_cap_reads_body(monkeypatch, hc_state):
    """http_client.py:162->173 — a numeric Content-Length within the cap proceeds to read the body."""
    monkeypatch.setattr(hc.time, "sleep", lambda *a, **k: None)
    resp = _HcCLResponse("5", [b"abc", b"de"])
    session = _HcSession(resp)

    out = hc._http_get(session, "https://anime-sama.to/x")

    assert out is resp
    assert out._content == b"abcde"
    assert resp.closed is True


class _HcAsyncResponse:
    def __init__(self, content_length: str, chunks) -> None:
        self.status_code = 200
        self.is_success = True
        self.headers = {"Content-Length": content_length}
        self._chunks = list(chunks)

    async def aiter_bytes(self, size):
        for c in self._chunks:
            yield c


class _HcAsyncCtx:
    def __init__(self, resp) -> None:
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class _HcAsyncClient:
    def __init__(self, resp) -> None:
        self._resp = resp
        self.calls = 0

    def stream(self, method, url, **kwargs):
        self.calls += 1
        return _HcAsyncCtx(self._resp)


def test_http_get_async_content_length_within_cap_reads_body(monkeypatch):
    """http_client.py:289->293 — a numeric Content-Length within the cap proceeds to read the body."""
    resp = _HcAsyncResponse("4", [b"ab", b"cd"])
    client = _HcAsyncClient(resp)

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)

    out = asyncio.run(hc._http_get_async("https://anime-sama.to/x", None))

    assert isinstance(out, hc._AsyncResp)
    assert out.text == "abcd"
    assert client.calls == 1


