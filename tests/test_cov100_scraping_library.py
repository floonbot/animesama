import asyncio
import json

import pytest

import engine.library.scanner as scanner_mod
import engine.library.updates as updates_mod
import engine.scraping.anilist as anilist_mod
import engine.scraping.episodes as ep_mod
import engine.scraping.favorites as favorites_mod
import engine.scraping.parser as parser_pkg
import engine.scraping.scan as scan_mod
import engine.scraping.search as search_mod
from engine.auth.manager import auth_manager
from engine.scraping.parser._base import _make_soup
from engine.scraping.parser.episodes import (
    _nb_episodes_depuis_options,
    parse_episodes,
)
from engine.scraping.parser.search import parse_search_results
from engine.scraping.site.animessama import COVERS_BASE, SITE_URL


class _Resp:
    def __init__(self, text):
        self.text = text


class _Disk:
    def __init__(self):
        self.store = {}
        self.get_calls = []
        self.set_many_calls = []

    def get(self, key):
        self.get_calls.append(key)
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value

    def set_many(self, items):
        self.set_many_calls.append(dict(items))
        self.store.update(items)


class _Cache:
    def __init__(self, get_ep_seq=None):
        self.mem = {}
        self.set_ep_calls = []
        self._get_ep_seq = get_ep_seq

    def get_ep(self, key):
        if self._get_ep_seq is not None:
            return self._get_ep_seq(key)
        return self.mem.get(key)

    def set_ep(self, key, data):
        self.set_ep_calls.append((key, data))
        self.mem[key] = data

    def ep_lock(self, key):
        return asyncio.Lock()


@pytest.fixture(autouse=True)
def _restore_episodes_globals():
    orig_disk = ep_mod._ep_disk
    orig_cache = ep_mod.cache
    orig_http = ep_mod.http_get
    orig_safe = ep_mod._is_safe_url
    orig_cookies = auth_manager.cookies
    orig_parse_saisons = parser_pkg.parse_saisons
    orig_parse_episodes = parser_pkg.parse_episodes
    yield
    ep_mod._ep_disk = orig_disk
    ep_mod.cache = orig_cache
    ep_mod.http_get = orig_http
    ep_mod._is_safe_url = orig_safe
    auth_manager.cookies = orig_cookies
    parser_pkg.parse_saisons = orig_parse_saisons
    parser_pkg.parse_episodes = orig_parse_episodes


def _install_ep(monkeypatch, *, disk=None, cache=None, safe=True, cookies=None):
    disk = disk if disk is not None else _Disk()
    cache = cache if cache is not None else _Cache()
    monkeypatch.setattr(ep_mod, "_ep_disk", disk)
    monkeypatch.setattr(ep_mod, "cache", cache)
    monkeypatch.setattr(ep_mod, "_is_safe_url", lambda u: safe)
    monkeypatch.setattr(auth_manager, "cookies", cookies if cookies is not None else [])
    return disk, cache


def test_get_episodes_prepends_site_url_for_leading_slash(monkeypatch):
    disk, cache = _install_ep(monkeypatch)
    seen = []

    async def _http_get(url, cookies):
        seen.append(url)
        return _Resp("<fiche>")

    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    parsed = {"titre": "Naruto", "episodes": [{"n": 1}], "langues": ["vf"]}
    saisons = [
        {"saison": 1, "url": f"{SITE_URL}/catalogue/naruto/saison1/vf", "_parsed": parsed},
        {"saison": 2, "url": f"{SITE_URL}/catalogue/naruto/saison2/vf", "_parsed": parsed},
    ]
    monkeypatch.setattr(parser_pkg, "parse_saisons", lambda html: saisons)

    out = asyncio.run(ep_mod.get_episodes_async("/catalogue/naruto/saison1/vf"))
    assert out["total"] == 2
    assert seen[0] == f"{SITE_URL}/catalogue/naruto"


def test_get_episodes_inner_lock_mem_cache_hit(monkeypatch):
    disk = _Disk()
    key = f"{SITE_URL}/catalogue/naruto"
    cached = {"titre": "T", "episodes": [{"n": 1}], "langues": ["vf"], "total": 1}
    state = {"calls": 0}

    def _seq(k):
        if k == key:
            state["calls"] += 1
            if state["calls"] == 1:
                return None
            return cached
        return None

    cache = _Cache(get_ep_seq=_seq)
    _install_ep(monkeypatch, disk=disk, cache=cache)

    def _boom(*a, **k):
        raise AssertionError("http_get must not run when inner cache hits")

    monkeypatch.setattr(ep_mod, "http_get", _boom)
    out = asyncio.run(ep_mod.get_episodes_async(f"{SITE_URL}/catalogue/naruto"))
    assert out == cached
    assert state["calls"] == 2
    assert disk.get_calls == []


def test_get_episodes_fiche_mem_cache_hit(monkeypatch):
    disk = _Disk()
    cache_key = f"{SITE_URL}/catalogue/naruto/saison1/vf"
    fiche_key = f"{SITE_URL}/catalogue/naruto"
    cached_fiche = {"titre": "T", "episodes": [{"n": 1}], "langues": ["vf"], "total": 1}

    def _seq(k):
        if k == fiche_key:
            return cached_fiche
        return None

    cache = _Cache(get_ep_seq=_seq)
    _install_ep(monkeypatch, disk=disk, cache=cache)

    def _boom(*a, **k):
        raise AssertionError("http_get must not run when fiche cache hits")

    monkeypatch.setattr(ep_mod, "http_get", _boom)
    out = asyncio.run(ep_mod.get_episodes_async(cache_key))
    assert out == cached_fiche


def test_get_episodes_fiche_disk_cache_hit(monkeypatch):
    cache_key = f"{SITE_URL}/catalogue/naruto/saison1/vf"
    fiche_key = f"{SITE_URL}/catalogue/naruto"
    disk = _Disk()
    cached_fiche = {"titre": "T", "episodes": [{"n": 2}], "langues": ["vf"], "total": 1}
    disk.store[fiche_key] = cached_fiche
    cache = _Cache()
    _install_ep(monkeypatch, disk=disk, cache=cache)

    def _boom(*a, **k):
        raise AssertionError("http_get must not run when fiche disk cache hits")

    monkeypatch.setattr(ep_mod, "http_get", _boom)
    out = asyncio.run(ep_mod.get_episodes_async(cache_key))
    assert out == cached_fiche
    assert (fiche_key, cached_fiche) in cache.set_ep_calls


def test_get_episodes_no_saison_no_saison_path_returns_empty(monkeypatch):
    disk, cache = _install_ep(monkeypatch)
    monkeypatch.setattr(ep_mod.time, "time", lambda: 1000.0)

    async def _http_get(u, cookies):
        return _Resp("<fiche>")

    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    monkeypatch.setattr(parser_pkg, "parse_saisons", lambda html: [])
    monkeypatch.setattr(parser_pkg, "parse_episodes", lambda text, url: {"episodes": []})

    out = asyncio.run(ep_mod.get_episodes_async(f"{SITE_URL}/catalogue/naruto"))
    assert out == {"titre": "", "episodes": [], "langues": [], "total": 0}


def test_get_episodes_truncates_more_than_20_saisons(monkeypatch):
    disk, cache = _install_ep(monkeypatch)

    async def _http_get(url, cookies):
        return _Resp("<fiche>")

    monkeypatch.setattr(ep_mod, "http_get", _http_get)

    saisons = [
        {
            "saison": n,
            "url": f"{SITE_URL}/catalogue/naruto/saison{n}/vf",
            "_parsed": {"titre": "Naruto", "episodes": [{"n": n}], "langues": ["vf"]},
        }
        for n in range(1, 26)
    ]
    monkeypatch.setattr(parser_pkg, "parse_saisons", lambda html: saisons)

    out = asyncio.run(ep_mod.get_episodes_async(f"{SITE_URL}/catalogue/naruto/saison1/vf"))
    assert out["total"] == 20


def test_get_episodes_fetches_saison_pages_when_not_parsed(monkeypatch):
    disk, cache = _install_ep(monkeypatch)

    season_url = f"{SITE_URL}/catalogue/naruto/saison1/vf"

    async def _http_get(url, cookies):
        if url == f"{SITE_URL}/catalogue/naruto":
            return _Resp("<fiche>")
        if url == season_url:
            return _Resp("<saison>")
        return None

    monkeypatch.setattr(ep_mod, "http_get", _http_get)

    saisons = [{"saison": 1, "url": season_url, "lang": "vf"}, {"saison": 2, "url": season_url, "lang": "vf"}]
    monkeypatch.setattr(parser_pkg, "parse_saisons", lambda html: saisons)

    def _parse_episodes(text, url):
        if text == "<saison>":
            return {"titre": "Naruto", "episodes": [{"n": 1}], "langues": ["vf"]}
        return {"titre": "", "episodes": [], "langues": []}

    monkeypatch.setattr(parser_pkg, "parse_episodes", _parse_episodes)

    out = asyncio.run(ep_mod.get_episodes_async(season_url))
    assert out["titre"] == "Naruto"
    assert out["episodes"] == [{"n": 1}, {"n": 1}]


def test_get_episodes_skips_none_part_when_http_get_returns_none(monkeypatch):
    disk, cache = _install_ep(monkeypatch)

    good_url = f"{SITE_URL}/catalogue/naruto/saison1/vf"
    bad_url = f"{SITE_URL}/catalogue/naruto/saison2/vf"

    async def _http_get(url, cookies):
        if url == f"{SITE_URL}/catalogue/naruto":
            return _Resp("<fiche>")
        if url == good_url:
            return _Resp("<saison1>")
        return None

    monkeypatch.setattr(ep_mod, "http_get", _http_get)

    saisons = [
        {"saison": 1, "url": good_url, "lang": "vf"},
        {"saison": 2, "url": bad_url, "lang": "vf"},
    ]
    monkeypatch.setattr(parser_pkg, "parse_saisons", lambda html: saisons)

    def _parse_episodes(text, url):
        if text == "<saison1>":
            return {"titre": "Naruto", "episodes": [{"n": 1}], "langues": ["vf"]}
        return {"titre": "", "episodes": [], "langues": []}

    monkeypatch.setattr(parser_pkg, "parse_episodes", _parse_episodes)

    out = asyncio.run(ep_mod.get_episodes_async(good_url))
    assert out["episodes"] == [{"n": 1}]
    assert out["total"] == 1


def test_get_episodes_timeout_with_no_episodes_returns_empty(monkeypatch):
    disk, cache = _install_ep(monkeypatch)

    async def _http_get(url, cookies):
        return _Resp("<fiche>")

    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    saisons = [
        {"saison": 1, "url": f"{SITE_URL}/catalogue/naruto/saison1/vf", "_parsed": {"episodes": []}},
    ]
    monkeypatch.setattr(parser_pkg, "parse_saisons", lambda html: saisons)

    async def _fake_wait_for(coro, timeout):
        await coro
        raise TimeoutError

    monkeypatch.setattr(ep_mod.asyncio, "wait_for", _fake_wait_for)

    out = asyncio.run(ep_mod.get_episodes_async(f"{SITE_URL}/catalogue/naruto/saison1/vf"))
    assert out == {"titre": "", "episodes": [], "langues": [], "total": 0}


def test_get_episodes_empty_after_gather_returns_empty(monkeypatch):
    disk, cache = _install_ep(monkeypatch)

    async def _http_get(url, cookies):
        return _Resp("<fiche>")

    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    saisons = [
        {"saison": 1, "url": f"{SITE_URL}/catalogue/naruto/saison1/vf", "_parsed": {"episodes": []}},
    ]
    monkeypatch.setattr(parser_pkg, "parse_saisons", lambda html: saisons)

    out = asyncio.run(ep_mod.get_episodes_async(f"{SITE_URL}/catalogue/naruto/saison1/vf"))
    assert out == {"titre": "", "episodes": [], "langues": [], "total": 0}
    assert cache.set_ep_calls == []


def test_lister_sondage_breaks_after_three_empties_below_known(monkeypatch):
    monkeypatch.setattr(ep_mod.time, "time", lambda: 1000.0)
    requested = []

    async def _http_get(url, cookies):
        requested.append(url)
        return _Resp(url)

    monkeypatch.setattr(ep_mod, "http_get", _http_get)
    monkeypatch.setattr(parser_pkg, "parse_episodes", lambda text, url: {"episodes": []})

    out = asyncio.run(
        ep_mod._lister_saisons_par_sondage([], "naruto", "vostfr", saison_max_connu=10)
    )
    assert out == []
    assert requested == [
        f"{SITE_URL}/catalogue/naruto/saison1/vostfr",
        f"{SITE_URL}/catalogue/naruto/saison1/vostfr/episodes.js",
        f"{SITE_URL}/catalogue/naruto/saison2/vostfr",
        f"{SITE_URL}/catalogue/naruto/saison2/vostfr/episodes.js",
        f"{SITE_URL}/catalogue/naruto/saison3/vostfr",
        f"{SITE_URL}/catalogue/naruto/saison3/vostfr/episodes.js",
    ]


def test_parse_episodes_no_episodes_returns_titre_only():
    html = '<html><head><title>Anime-Sama - MyShow</title></head><body></body></html>'
    out = parse_episodes(html, f"{SITE_URL}/catalogue/x/saison1/vostfr")
    assert out == {"titre": "MyShow", "episodes": [], "langues": [], "total": 0}


def test_parse_episodes_builds_episode_urls_with_relative_base():
    html = 'var eps1=["https://a.tld/1","https://b.tld/2"]'
    out = parse_episodes(html, "/catalogue/x/saison2/vf?ep=1")
    assert out["total"] == 2
    assert out["langues"] == ["VF"]
    first = out["episodes"][0]
    assert first["url"] == f"{SITE_URL}/catalogue/x/saison2/vf?ep=1"
    assert first["saison"] == 2
    assert first["episode"] == 1
    assert out["episodes"][1]["url"] == f"{SITE_URL}/catalogue/x/saison2/vf?ep=2"


def test_nb_episodes_depuis_options_counts_options():
    html = (
        '<select id="selectEpisodes">'
        "<option>1</option><option>2</option><option>3</option></select>"
    )
    soup = _make_soup(html)
    assert _nb_episodes_depuis_options(soup) == 3


def test_parse_search_results_falls_back_to_slug_title_and_cover():
    html = '<a href="/catalogue/one-piece"></a>'
    out = parse_search_results(html)
    assert len(out) == 1
    assert out[0]["nom"] == "One Piece"
    assert out[0]["image"] == f"{COVERS_BASE}/one-piece.jpg"
    assert out[0]["url"] == SITE_URL + "/catalogue/one-piece"


def test_parse_search_results_status_from_badge():
    html = (
        '<a href="/catalogue/naruto"><h2>Naruto</h2>'
        '<span class="badge">vostfr</span></a>'
    )
    out = parse_search_results(html)
    assert out[0]["statut"] == "VOSTFR"


@pytest.fixture(autouse=True)
def _restore_anilist_globals():
    orig_enabled = anilist_mod._ENABLED
    orig_disk = anilist_mod._disk
    yield
    anilist_mod._ENABLED = orig_enabled
    anilist_mod._disk = orig_disk


class _AnilistDisk:
    def __init__(self, get_value=None):
        self.get_value = get_value
        self.set_calls = []

    def get(self, key):
        return self.get_value

    def set(self, key, value):
        self.set_calls.append((key, value))


def test_canon_saison1_empty_key_returns_none(monkeypatch):
    monkeypatch.setattr(anilist_mod, "_ENABLED", True)

    def _boom(_titre):
        raise AssertionError("_fetch_sync must not run for an empty key")

    monkeypatch.setattr(anilist_mod, "_fetch_sync", _boom)
    assert anilist_mod.canon_saison1("!!!") is None


def test_canon_saison1_fetch_none_returns_none(monkeypatch):
    disk = _AnilistDisk(get_value=None)
    monkeypatch.setattr(anilist_mod, "_disk", disk)
    monkeypatch.setattr(anilist_mod, "_ENABLED", True)
    monkeypatch.setattr(anilist_mod, "_fetch_sync", lambda _t: None)
    assert anilist_mod.canon_saison1("Bleach") is None
    assert disk.set_calls == []


def test_canon_saison1_no_match_caches_unmatched(monkeypatch):
    disk = _AnilistDisk(get_value=None)
    monkeypatch.setattr(anilist_mod, "_disk", disk)
    monkeypatch.setattr(anilist_mod, "_ENABLED", True)
    media = {"title": {"romaji": "Totally Other", "english": "Other"}, "episodes": 12, "status": "FINISHED"}
    monkeypatch.setattr(anilist_mod, "_fetch_sync", lambda _t: media)
    out = anilist_mod.canon_saison1("Bleach")
    assert out == {"matched": False, "episodes": None, "finished": False}
    assert disk.set_calls == [(anilist_mod._norm("Bleach"), out)]


@pytest.fixture(autouse=True)
def _restore_favorites_globals():
    orig_cache = favorites_mod.cache
    orig_http = favorites_mod.http_get
    yield
    favorites_mod.cache = orig_cache
    favorites_mod.http_get = orig_http


class _FavCache:
    def __init__(self, fresh=False, favs=None, lock=None):
        self._fresh = fresh
        self._favs = favs if favs is not None else []
        self._lock = lock
        self.saved = None

    def fav_fresh(self):
        return self._fresh

    def get_fav(self):
        return self._favs

    def fav_lock(self):
        return self._lock

    def set_fav(self, value):
        self.saved = value


def test_favorites_returns_cached_when_fresh_logs_count(monkeypatch):
    monkeypatch.setattr(auth_manager, "_logged_in", True)
    cached = [{"titre": "Naruto"}]
    monkeypatch.setattr(favorites_mod, "cache", _FavCache(fresh=True, favs=cached))

    async def _boom(url, cookies):
        raise AssertionError("http_get must not run on a fresh cache hit")

    monkeypatch.setattr(favorites_mod, "http_get", _boom)
    out = asyncio.run(favorites_mod.get_favorites_async())
    assert out == cached


def test_favorites_inner_fresh_short_circuit(monkeypatch):
    monkeypatch.setattr(auth_manager, "_logged_in", True)
    cached = [{"titre": "X"}]

    class _SeqCache(_FavCache):
        def __init__(self):
            super().__init__(fresh=False, favs=cached, lock=asyncio.Lock())
            self._fresh_seq = iter([False, True])

        def fav_fresh(self):
            return next(self._fresh_seq)

    monkeypatch.setattr(favorites_mod, "cache", _SeqCache())

    async def _boom(url, cookies):
        raise AssertionError("http_get must not run when the inner fresh check passes")

    monkeypatch.setattr(favorites_mod, "http_get", _boom)
    out = asyncio.run(favorites_mod.get_favorites_async())
    assert out == cached


def test_favorites_relogin_succeeds_but_refetch_still_disconnected(monkeypatch):
    monkeypatch.setattr(auth_manager, "_logged_in", True)
    monkeypatch.setattr(favorites_mod, "cache", _FavCache(fresh=False, lock=asyncio.Lock()))

    gets = {"n": 0}

    async def _get(url, cookies):
        gets["n"] += 1
        return _Resp('{"logged_in": false}')

    monkeypatch.setattr(favorites_mod, "http_get", _get)

    async def _relogin_ok():
        return True

    monkeypatch.setattr(auth_manager, "re_login_if_needed", _relogin_ok)

    def _boom_parse(data):
        raise AssertionError("parse_favoris_api must not run when still disconnected")

    monkeypatch.setattr("engine.scraping.parser.parse_favoris_api", _boom_parse)

    out = asyncio.run(favorites_mod.get_favorites_async())
    assert out == []
    assert gets["n"] == 2


def test_scanner_est_dans_downloads_rejects_non_string():
    assert scanner_mod.est_dans_downloads("") is False
    assert scanner_mod.est_dans_downloads(123) is False


def test_scanner_est_dans_downloads_resolve_failure_returns_false(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("dossiers_actifs must not run when cible.resolve fails")

    monkeypatch.setattr(scanner_mod, "dossiers_actifs", _boom)

    class _BadPath:
        def resolve(self):
            raise OSError("no resolve")

    monkeypatch.setattr(scanner_mod, "Path", lambda f: _BadPath())
    assert scanner_mod.est_dans_downloads("/x/y.mp4") is False


def test_scan_un_dossier_missing_root_returns_empty(tmp_path):
    missing = tmp_path / "ghost"
    animes, tronque = scanner_mod._scan_un_dossier(missing)
    assert animes == {}
    assert tronque is False


def test_scan_un_dossier_iterdir_oserror_returns_empty(monkeypatch, tmp_path):
    racine = tmp_path / "root"
    racine.mkdir()

    class _Root:
        def __init__(self, real):
            self._real = real
            self.name = real.name

        def exists(self):
            return True

        def iterdir(self):
            raise PermissionError("denied")

        def __fspath__(self):
            return str(self._real)

    animes, tronque = scanner_mod._scan_un_dossier(_Root(racine))
    assert animes == {}
    assert tronque is False


def test_scan_un_dossier_skips_underscore_dir(tmp_path):
    (tmp_path / "_hidden" / "Saison 01").mkdir(parents=True)
    (tmp_path / "_hidden" / "Saison 01" / "E1.mp4").write_bytes(b"x" * 4)
    (tmp_path / "Show" / "Saison 01").mkdir(parents=True)
    (tmp_path / "Show" / "Saison 01" / "E1.mp4").write_bytes(b"x" * 4)

    animes, _ = scanner_mod._scan_un_dossier(tmp_path)
    assert "_hidden" not in animes
    assert "Show" in animes


class _AnimeDir:
    def __init__(self, key, name, *, raise_is_dir=False):
        self._key = key
        self.name = name
        self._raise = raise_is_dir

    def __lt__(self, other):
        return self.name < other.name

    def __str__(self):
        return self._key

    def __fspath__(self):
        return self._key

    def is_dir(self):
        if self._raise:
            raise OSError("is_dir denied")
        return True


class _RootIter:
    def __init__(self, entries):
        self._entries = entries

    def exists(self):
        return True

    def iterdir(self):
        return list(self._entries)


class _ScanEntry:
    def __init__(self, name, path, *, is_dir_val=True, raise_is_dir=False,
                 raise_stat=False, st_mode=None):
        self.name = name
        self.path = path
        self._is_dir_val = is_dir_val
        self._raise_is_dir = raise_is_dir
        self._raise_stat = raise_stat
        self._st_mode = st_mode

    def is_dir(self, follow_symlinks=True):
        if self._raise_is_dir:
            raise OSError("is_dir denied")
        return self._is_dir_val

    def stat(self):
        if self._raise_stat:
            raise OSError("stat denied")
        import types

        return types.SimpleNamespace(st_mode=self._st_mode, st_size=10, st_mtime=1.0)


def _scandir_router(mapping):
    def _scandir(path):
        key = str(path)
        if key in mapping:
            value = mapping[key]
            if isinstance(value, Exception):
                raise value
            return iter(value)
        raise FileNotFoundError(key)

    return _scandir


def test_scan_un_dossier_anime_dir_is_dir_oserror_skipped(monkeypatch):
    root = _RootIter([_AnimeDir("X:/anime", "Boom", raise_is_dir=True)])

    def _boom_scandir(_p):
        raise AssertionError("scandir must not run when anime is_dir raises")

    monkeypatch.setattr(scanner_mod.os, "scandir", _boom_scandir)
    animes, tronque = scanner_mod._scan_un_dossier(root)
    assert animes == {}
    assert tronque is False


def test_scan_un_dossier_season_is_dir_oserror_skipped(monkeypatch):
    anime = _AnimeDir("X:/anime", "Show")
    season = _ScanEntry("S1", "X:/anime/S1", raise_is_dir=True)
    root = _RootIter([anime])
    mapping = {"X:/anime": [season]}

    monkeypatch.setattr(scanner_mod.os, "scandir", _scandir_router(mapping))
    animes, _ = scanner_mod._scan_un_dossier(root)
    assert animes == {}


def test_scan_un_dossier_inner_scandir_oserror_skipped(monkeypatch):
    anime = _AnimeDir("X:/anime", "Show")
    season = _ScanEntry("S1", "X:/anime/S1", is_dir_val=True)
    root = _RootIter([anime])

    mapping = {
        "X:/anime": [season],
        "X:/anime/S1": PermissionError("denied"),
    }
    monkeypatch.setattr(scanner_mod.os, "scandir", _scandir_router(mapping))
    animes, _ = scanner_mod._scan_un_dossier(root)
    assert animes == {}


def test_scan_un_dossier_file_stat_oserror_skipped(monkeypatch):
    anime = _AnimeDir("X:/anime", "Show")
    season = _ScanEntry("S1", "X:/anime/S1", is_dir_val=True)
    bad_file = _ScanEntry("E1.mp4", "X:/anime/S1/E1.mp4", raise_stat=True)
    root = _RootIter([anime])

    mapping = {
        "X:/anime": [season],
        "X:/anime/S1": [bad_file],
    }
    monkeypatch.setattr(scanner_mod.os, "scandir", _scandir_router(mapping))
    animes, _ = scanner_mod._scan_un_dossier(root)
    assert animes == {}


def test_scan_un_dossier_skips_non_regular_file(monkeypatch):
    import stat as _stat

    anime = _AnimeDir("X:/anime", "Show")
    season = _ScanEntry("S1", "X:/anime/S1", is_dir_val=True)
    dir_named_video = _ScanEntry(
        "weird.mkv", "X:/anime/S1/weird.mkv", st_mode=_stat.S_IFDIR
    )
    real_file = _ScanEntry(
        "real.mp4", "X:/anime/S1/real.mp4", st_mode=_stat.S_IFREG
    )
    root = _RootIter([anime])

    mapping = {
        "X:/anime": [season],
        "X:/anime/S1": [dir_named_video, real_file],
    }
    monkeypatch.setattr(scanner_mod.os, "scandir", _scandir_router(mapping))
    animes, _ = scanner_mod._scan_un_dossier(root)
    eps = animes["Show"]["saisons"][0]["episodes"]
    assert {e["nom"] for e in eps} == {"real"}


def test_charger_exceptions_updates_normalises_and_drops_non_dict(monkeypatch, tmp_path):
    import engine.config.settings as settings_mod

    payload = {
        "Demon Slayer Saison 2": {"saisons_ignorees": [3]},
        "Bad": ["not", "a", "dict"],
    }
    (tmp_path / "ignore_updates.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    out = updates_mod.charger_exceptions_updates()
    assert out == {"demon slayer": {"saisons_ignorees": [3]}}


def test_ep_est_ignore_non_int_saison_swallowed():
    regle = {"saisons_ignorees": ["abc"]}
    assert updates_mod.ep_est_ignore(regle, 1, 1) is False


def test_ep_est_ignore_non_int_episode_swallowed():
    regle = {"episodes_ignores": {"1": ["xx"]}}
    assert updates_mod.ep_est_ignore(regle, 1, 1) is False


@pytest.fixture(autouse=True)
def _reset_updates_cache():
    updates_mod.invalider_cache_updates()
    yield
    updates_mod.invalider_cache_updates()


def _async_return(value):
    async def _coro(*a, **k):
        return value

    return _coro


def test_check_updates_counts_errors_from_gather(monkeypatch):
    import engine.auth.manager as auth_mod
    import engine.scraping.scraper as scraper_mod

    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", True)

    librairie = {
        "animes": [
            {"nom": "Boom", "saisons": [{"episodes": [{"nom": "Boom - S01E001"}]}]},
        ]
    }
    favoris = [{"nom": "Boom", "url": "http://site/boom"}]
    monkeypatch.setattr(scanner_mod, "scan_librairie_sync", lambda: librairie)
    monkeypatch.setattr(scraper_mod, "get_favorites_async", _async_return(favoris))

    async def _explode(url, force_refresh=False):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(scraper_mod, "get_episodes_async", _explode)
    real_gather = asyncio.gather

    async def _gather(*coros, return_exceptions=False):
        if return_exceptions:
            for c in coros:
                c.close()
            return [RuntimeError("forced")]
        return await real_gather(*coros)

    monkeypatch.setattr(updates_mod.asyncio, "gather", _gather)

    out = asyncio.run(updates_mod.check_updates_async())
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0


def test_check_updates_per_anime_timeout_excluded(monkeypatch):
    import engine.auth.manager as auth_mod
    import engine.scraping.scraper as scraper_mod

    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", True)

    librairie = {
        "animes": [
            {"nom": "Slow", "saisons": [{"episodes": [{"nom": "Slow - S01E001"}]}]},
        ]
    }
    favoris = [{"nom": "Slow", "url": "http://site/slow"}]
    monkeypatch.setattr(scanner_mod, "scan_librairie_sync", lambda: librairie)
    monkeypatch.setattr(scraper_mod, "get_favorites_async", _async_return(favoris))

    async def _eps(url, force_refresh=False):
        return {"episodes": [{"saison": 1, "episode": 2, "url": "u2"}]}

    monkeypatch.setattr(scraper_mod, "get_episodes_async", _eps)

    real_wait_for = asyncio.wait_for

    async def _wait_for(coro, timeout):
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(updates_mod.asyncio, "wait_for", _wait_for)

    out = asyncio.run(updates_mod.check_updates_async())
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0
    assert real_wait_for is not None


@pytest.fixture(autouse=True)
def _reset_scan_info_cache():
    with scan_mod._scan_info_lock:
        snapshot = dict(scan_mod._scan_info_cache)
        scan_mod._scan_info_cache.clear()
    yield
    with scan_mod._scan_info_lock:
        scan_mod._scan_info_cache.clear()
        scan_mod._scan_info_cache.update(snapshot)


class _StreamRespClose:
    def __init__(self, status_code=200, chunks=None, encoding="utf-8"):
        self.status_code = status_code
        self.encoding = encoding
        self._chunks = chunks if chunks is not None else []
        self.close_calls = 0

    def iter_content(self, _size):
        yield from self._chunks

    def close(self):
        self.close_calls += 1
        raise OSError("close failed")


class _SessionFixed:
    def __init__(self, response):
        self._response = response

    def get(self, url, headers=None, timeout=None, stream=None):
        return self._response


def test_scan_info_set_evicts_stale_keys(monkeypatch):
    times = {"now": 1000.0}
    monkeypatch.setattr(scan_mod.time, "time", lambda: times["now"])

    for i in range(201):
        scan_mod._scan_info_set(f"old{i}", {"v": i})

    times["now"] = 1000.0 + scan_mod._SCAN_INFO_TTL + 1
    scan_mod._scan_info_set("fresh", {"v": "f"})

    assert "fresh" in scan_mod._scan_info_cache
    assert all(not k.startswith("old") for k in scan_mod._scan_info_cache)


def test_fetch_text_close_exception_swallowed(monkeypatch):
    resp = _StreamRespClose(status_code=200, chunks=[b"abc"])
    monkeypatch.setattr(scan_mod, "_get_session", lambda _h: _SessionFixed(resp))

    status, text = scan_mod._fetch_text("http://x/y", max_bytes=100)
    assert status == 200
    assert text == "abc"
    assert resp.close_calls == 1


def test_get_scan_info_sync_skips_empty_chapter_keys(monkeypatch):
    page_html = (
        '<html><body>'
        '<h3 id="titreOeuvre">My Work</h3>'
        '<select id="selectChapitres"><option>Chapitre 1</option></select>'
        '</body></html>'
    )

    def fake_fetch(url, referer=None, max_bytes=0):
        if "/scan/vf" in url:
            return 200, page_html
        return -1, ""

    monkeypatch.setattr(scan_mod, "_fetch_text", fake_fetch)
    monkeypatch.setattr(
        scan_mod, "_fetch_api_retry",
        lambda url, referer=None: json.dumps({"1": 10, "  ": 5, "2": 8}),
    )

    class _NoDisk:
        def get(self, key):
            return None

        def set(self, key, value):
            pass

    monkeypatch.setattr(scan_mod, "_scan_disk", _NoDisk())

    out = scan_mod.get_scan_info_sync("good-slug", "vf")
    assert out["ok"] is True
    assert [c["num"] for c in out["chapitres"]] == ["1", "2"]
    assert out["total"] == 2


def test_get_pages_sync_edge_cases_return_empty(monkeypatch):
    assert scan_mod.get_pages_sync("", "1", "vf") == []
    assert scan_mod.get_pages_sync("X", "", "vf") == []

    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda url, referer=None: None)
    assert scan_mod.get_pages_sync("X", "1", "vf") == []

    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda url, referer=None: "not json")
    assert scan_mod.get_pages_sync("X", "1", "vf") == []

    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda url, referer=None: json.dumps(["a", "b"]))
    assert scan_mod.get_pages_sync("X", "1", "vf") == []

    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda url, referer=None: json.dumps({"1": "notnum"}))
    assert scan_mod.get_pages_sync("X", "1", "vf") == []

    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda url, referer=None: json.dumps({"1": 0}))
    assert scan_mod.get_pages_sync("X", "1", "vf") == []


def test_get_scan_info_async_delegates_to_thread(monkeypatch):
    captured = {}

    def _sync(slug, lang):
        captured["args"] = (slug, lang)
        return {"ok": True, "slug": slug}

    monkeypatch.setattr(scan_mod, "get_scan_info_sync", _sync)
    out = asyncio.run(scan_mod.get_scan_info("the-slug", "va"))
    assert out == {"ok": True, "slug": "the-slug"}
    assert captured["args"] == ("the-slug", "va")


def test_get_pages_async_delegates_to_thread(monkeypatch):
    captured = {}

    def _sync(oeuvre, chap, lang):
        captured["args"] = (oeuvre, chap, lang)
        return [{"page": 1, "url": "u"}]

    monkeypatch.setattr(scan_mod, "get_pages_sync", _sync)
    out = asyncio.run(scan_mod.get_pages("Oeuvre", "5", "vf"))
    assert out == [{"page": 1, "url": "u"}]
    assert captured["args"] == ("Oeuvre", "5", "vf")


@pytest.fixture(autouse=True)
def _restore_search_globals():
    saved_cache = dict(search_mod._types_cache)
    saved_loaded = search_mod._types_loaded
    saved_http = search_mod.http_get
    saved_safe = search_mod._is_safe_url
    saved_file = search_mod._TYPES_FILE
    saved_save = search_mod._save_types_cache
    yield
    search_mod._types_cache.clear()
    search_mod._types_cache.update(saved_cache)
    search_mod._types_loaded = saved_loaded
    search_mod.http_get = saved_http
    search_mod._is_safe_url = saved_safe
    search_mod._TYPES_FILE = saved_file
    search_mod._save_types_cache = saved_save


def test_load_types_cache_swallows_read_error(monkeypatch, tmp_path):
    bad = tmp_path / "scan_types.json"
    bad.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(search_mod, "_TYPES_FILE", bad)
    monkeypatch.setattr(search_mod, "_types_loaded", False)
    with search_mod._types_cache_lock:
        search_mod._types_cache.clear()

    search_mod._load_types_cache()
    assert search_mod._types_cache == {}
    assert search_mod._types_loaded is True


def test_save_types_cache_swallows_oserror(monkeypatch, tmp_path):
    target = tmp_path / "nope" / "scan_types.json"
    monkeypatch.setattr(search_mod, "_TYPES_FILE", target)
    with search_mod._types_cache_lock:
        search_mod._types_cache.clear()
        search_mod._types_cache["https://x/a"] = "scan"

    search_mod._save_types_cache()
    assert not target.exists()


def test_detecter_types_skips_non_string_and_empty(monkeypatch):
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    with search_mod._types_cache_lock:
        search_mod._types_cache.clear()

    async def _boom(*a, **k):
        raise AssertionError("http_get must not run for invalid urls")

    monkeypatch.setattr(search_mod, "http_get", _boom)
    res = asyncio.run(search_mod.detecter_types_favoris_async([None, "", 123]))
    assert res == {}


def test_detecter_types_classifies_scan_only(monkeypatch):
    import engine.auth.manager as auth_mod

    class _AM:
        cookies = []

    monkeypatch.setattr(auth_mod, "auth_manager", _AM())
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    monkeypatch.setattr(search_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(search_mod, "_save_types_cache", lambda: None)
    with search_mod._types_cache_lock:
        search_mod._types_cache.clear()

    url = "https://anime-sama.to/catalogue/scanonly"

    class _R:
        text = "page"

        def __bool__(self):
            return True

    async def _get(u, cookies):
        return _R()

    monkeypatch.setattr(search_mod, "http_get", _get)
    monkeypatch.setattr(
        "engine.scraping.parser.detecter_type_contenu",
        lambda html: {"has_scan": True, "has_anime": False},
    )
    res = asyncio.run(search_mod.detecter_types_favoris_async([url]))
    assert res == {url: "scan"}


def test_detecter_types_http_get_none_yields_none_result(monkeypatch):
    import engine.auth.manager as auth_mod

    class _AM:
        cookies = []

    monkeypatch.setattr(auth_mod, "auth_manager", _AM())
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    monkeypatch.setattr(search_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(search_mod, "_save_types_cache", lambda: None)
    with search_mod._types_cache_lock:
        search_mod._types_cache.clear()

    url = "https://anime-sama.to/catalogue/empty"

    async def _get(u, cookies):
        return None

    def _boom_detect(html):
        raise AssertionError("detecter_type_contenu must not run on a None response")

    monkeypatch.setattr(search_mod, "http_get", _get)
    monkeypatch.setattr("engine.scraping.parser.detecter_type_contenu", _boom_detect)
    res = asyncio.run(search_mod.detecter_types_favoris_async([url]))
    assert res == {}
    assert url not in search_mod._types_cache


def test_detecter_types_none_result_skipped_and_lru_evicts(monkeypatch):
    import engine.auth.manager as auth_mod

    class _AM:
        cookies = []

    monkeypatch.setattr(auth_mod, "auth_manager", _AM())
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    monkeypatch.setattr(search_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(search_mod, "_save_types_cache", lambda: None)
    monkeypatch.setattr(search_mod, "_TYPES_MAX", 1)
    with search_mod._types_cache_lock:
        search_mod._types_cache.clear()
        search_mod._types_cache["https://anime-sama.to/catalogue/preexisting"] = "anime"

    good = "https://anime-sama.to/catalogue/good"
    bad = "https://anime-sama.to/catalogue/bad"

    async def _get(u, cookies):
        if "/bad" in u:
            raise RuntimeError("boom on bad")

        class _R:
            text = "page"

            def __bool__(self):
                return True

        return _R()

    monkeypatch.setattr(search_mod, "http_get", _get)
    monkeypatch.setattr(
        "engine.scraping.parser.detecter_type_contenu",
        lambda html: {"has_scan": False, "has_anime": True},
    )
    res = asyncio.run(search_mod.detecter_types_favoris_async([good, bad]))
    assert res[good] == "anime"
    assert bad not in res
    assert len(search_mod._types_cache) <= 1
