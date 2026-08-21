import asyncio
import logging
from urllib.parse import urlencode

from bs4 import SoupStrainer

from engine.scraping.http_client import http_get
from engine.scraping.parser._base import _attr_str, _make_soup
from engine.scraping.site.animessama import SITE_URL

log = logging.getLogger("engine.scraping.catalogue")

CATALOGUE_URL = f"{SITE_URL}/catalogue"
_STRAINER_GENRE = SoupStrainer("input", attrs={"name": "genre[]"})

def _construire_url(genre: str, type_: str, langue: str, statut: str, page: int) -> str:
    params: list[tuple[str, str]] = []
    for name, val in (("type[]", type_), ("langue[]", langue), ("genre[]", genre), ("current[]", statut)):
        v = (val or "").strip()
        if v:
            params.append((name, v))
    if page > 1:
        params.append(("page", str(page)))
    qs = urlencode(params)
    return CATALOGUE_URL + (f"?{qs}" if qs else "")

def _extraire_genres(html: str) -> list[str]:
    soup = _make_soup(html or "", parse_only=_STRAINER_GENRE)
    genres: list[str] = []
    seen: set[str] = set()
    for inp in soup.find_all("input"):
        val = _attr_str(inp, "value").strip()
        if val and val not in seen:
            seen.add(val)
            genres.append(val)
    return genres

async def catalogue_async(
    genre: str = "", type_: str = "", langue: str = "", statut: str = "", page: int = 1,
) -> list[dict]:
    from engine.auth.manager import auth_manager
    from engine.scraping.parser import parse_search_results

    try:
        page_n = max(1, int(page))
    except (TypeError, ValueError):
        page_n = 1

    url = _construire_url(genre, type_, langue, statut, page_n)
    try:
        r = await http_get(url, auth_manager.cookies)
        if not r:
            return []
        results = await asyncio.to_thread(parse_search_results, r.text)
        log.debug(f"catalogue_async : {len(results)} résultats (page {page_n})")
        return results
    except Exception as e:
        log.error(f"catalogue_async : {e}", exc_info=True)
        return []

async def catalogue_genres_async() -> list[str]:
    from engine.auth.manager import auth_manager
    try:
        r = await http_get(CATALOGUE_URL, auth_manager.cookies)
        if not r:
            return []
        return await asyncio.to_thread(_extraire_genres, r.text)
    except Exception as e:
        log.error(f"catalogue_genres_async : {e}", exc_info=True)
        return []
