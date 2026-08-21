import json
import logging

from engine.scraping._cache import cache
from engine.scraping.http_client import http_get
from engine.scraping.site.animessama import GETDATA_API

log = logging.getLogger("engine.scraping.favorites")

async def _fetch_library(cookies) -> dict | None:
    r = await http_get(GETDATA_API, cookies)
    if not r:
        return None
    try:
        data = json.loads(r.text)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None

async def get_favorites_async(force_refresh: bool = False) -> list[dict]:
    from engine.auth.manager import auth_manager
    from engine.scraping.parser import parse_favoris_api

    if not auth_manager.is_logged_in:
        return []

    if not force_refresh and cache.fav_fresh():
        log.debug(f"Favoris depuis cache ({len(cache.get_fav())} animes)")
        return cache.get_fav()

    lock = cache.fav_lock()
    if lock is None:
        log.error("get_favorites_async : impossible d'obtenir le lock asyncio")
        return []

    async with lock:
        if not force_refresh and cache.fav_fresh():
            return cache.get_fav()

        try:
            data = await _fetch_library(auth_manager.cookies)

            if data is None or not data.get("logged_in"):
                log.warning("Session expirée — tentative de re-login...")
                if not await auth_manager.re_login_if_needed():
                    return []
                data = await _fetch_library(auth_manager.cookies)
                if data is None or not data.get("logged_in"):
                    return []

            result = parse_favoris_api(data)
            cache.set_fav(result)
            log.debug(f"Favoris rafraîchis ({len(result)} animes)")
            return result

        except Exception as e:
            log.error(f"get_favorites_async : {e}", exc_info=True)
            return []
