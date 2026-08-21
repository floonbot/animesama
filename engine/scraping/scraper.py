import asyncio
import logging

from engine.scraping._cache import cache
from engine.scraping.episodes import get_episodes_async
from engine.scraping.favorites import get_favorites_async
from engine.scraping.http_client import _is_safe_url as is_site_url
from engine.scraping.http_client import clear_session_cache
from engine.scraping.players import get_lecteurs_async
from engine.scraping.search import detecter_types_favoris_async, search_async

log = logging.getLogger("engine.scraping.scraper")

async def invalidate_fav_cache() -> None:
    cache.invalidate_fav()
    log.debug("Cache favoris invalidé")

async def invalidate_ep_cache(url: str | None = None) -> None:
    from engine.scraping.episodes import invalidate_ep_disk

    cache.invalidate_ep(url)
    await asyncio.to_thread(invalidate_ep_disk, url)
    if url is None:
        log.debug("Cache épisodes entièrement invalidé")
    else:
        log.debug(f"Cache épisodes invalidé pour : {url.split('?')[0][:60]}")

def slug_valide(slug: str) -> bool:
    from engine.scraping.scan import slug_valide as _f
    return _f(slug)

async def get_scan_info(slug: str, lang: str) -> dict:
    from engine.scraping.scan import get_scan_info as _f
    return await _f(slug, lang)

async def get_pages(oeuvre: str, chap: str, lang: str) -> list:
    from engine.scraping.scan import get_pages as _f
    return await _f(oeuvre, chap, lang)

async def catalogue_async(
    genre: str = "", type_: str = "", langue: str = "", statut: str = "", page: int = 1,
) -> list[dict]:
    from engine.scraping.catalogue import catalogue_async as _f
    return await _f(genre=genre, type_=type_, langue=langue, statut=statut, page=page)

async def catalogue_genres_async() -> list[str]:
    from engine.scraping.catalogue import catalogue_genres_async as _f
    return await _f()

__all__ = [
    "get_favorites_async",
    "get_episodes_async",
    "get_lecteurs_async",
    "search_async",
    "detecter_types_favoris_async",
    "invalidate_fav_cache",
    "invalidate_ep_cache",
    "clear_session_cache",
    "is_site_url",
    "slug_valide",
    "get_scan_info",
    "get_pages",
    "catalogue_async",
    "catalogue_genres_async",
]
