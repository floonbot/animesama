import asyncio
import logging
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from engine.scraping.http_client import _is_safe_url, http_get
from engine.scraping.site.animessama import SITE_URL

log = logging.getLogger("engine.scraping.players")

_RE_FILEVER = re.compile(r"episodes\.js\?filever=(\d+)", re.I)


def url_episodes_js(saison_url: str, html: str = "") -> str:
    """URL du episodes.js d'une saison, avec le filever declare par sa page.

    Appele sans ce parametre, le site sert une copie de cache d'ou l'episode le
    plus recent est absent (mesure : 1059 o / 4 episodes contre 1293 o / 5).
    On reprend le filever du HTML plutot qu'un anti-cache maison : il est stable
    tant que le fichier ne bouge pas, donc le cache HTTP reste utile, alors qu'un
    parametre aleatoire taperait l'origine a chaque appel.
    """
    base = saison_url.split("?")[0].rstrip("/") + "/episodes.js"
    m = _RE_FILEVER.search(html or "")
    return f"{base}?filever={m.group(1)}" if m else base

_SEASON_CACHE_TTL = 600.0
_SEASON_CACHE_MAX = 16
_season_cache: dict[str, tuple[float, dict[str, list[str]]]] = {}
_season_cache_lock = threading.Lock()


def clear_season_cache() -> None:
    with _season_cache_lock:
        _season_cache.clear()


def _season_cache_get(key: str) -> dict[str, list[str]] | None:
    now = time.time()
    with _season_cache_lock:
        entry = _season_cache.get(key)
        if entry is None:
            return None
        ts, arrays = entry
        if now - ts >= _SEASON_CACHE_TTL:
            _season_cache.pop(key, None)
            return None
        return arrays


def _season_cache_set(key: str, arrays: dict[str, list[str]]) -> None:
    now = time.time()
    with _season_cache_lock:
        if len(_season_cache) >= _SEASON_CACHE_MAX and key not in _season_cache:
            oldest = min(_season_cache, key=lambda k: _season_cache[k][0])
            _season_cache.pop(oldest, None)
        _season_cache[key] = (now, arrays)


async def _fetch_saison_arrays(saison_url: str, cookies) -> tuple[dict[str, list[str]], bool]:
    from engine.scraping.parser._base import _extraire_eps_arrays

    # La page saison d'abord : c'est elle qui porte le filever du episodes.js.
    # Le compte de requetes ne bouge pas — une saison inexistante s'arrete ici
    # au lieu de tenter episodes.js puis la page.
    r_page = await http_get(saison_url, cookies)
    if not r_page:
        return {}, False

    url_js = url_episodes_js(saison_url, r_page.text)
    arrays_page = await asyncio.to_thread(_extraire_eps_arrays, r_page.text)
    if arrays_page and "filever=" not in url_js:
        return arrays_page, True

    r = await http_get(url_js, cookies)
    if r:
        arrays = await asyncio.to_thread(_extraire_eps_arrays, r.text)
        if arrays:
            return arrays, True
    return arrays_page, True


async def get_lecteurs_async(url_episode: str) -> list[dict]:
    from engine.auth.manager import auth_manager
    from engine.scraping.parser.players import lecteurs_depuis_arrays

    if not _is_safe_url(url_episode):
        log.warning(f"URL refusée : {(url_episode or '')[:60]}")
        return []

    if url_episode.startswith("/"):
        url_episode = SITE_URL + url_episode

    try:
        qs     = parse_qs(urlparse(url_episode).query)
        ep_num = int(qs.get("ep", ["1"])[0])
        if ep_num < 1:
            ep_num = 1
    except (ValueError, TypeError):
        ep_num = 1

    saison_url = url_episode.split("?")[0].rstrip("/")

    cached_arrays = _season_cache_get(saison_url)
    if cached_arrays is not None:
        return lecteurs_depuis_arrays(cached_arrays, ep_num)

    try:
        arrays, fetched_ok = await _fetch_saison_arrays(saison_url, auth_manager.cookies)
        if not fetched_ok:
            return []
        if arrays:
            _season_cache_set(saison_url, arrays)
        return lecteurs_depuis_arrays(arrays, ep_num)
    except Exception as e:
        log.error(f"get_lecteurs_async : {e}", exc_info=True)
        return []
