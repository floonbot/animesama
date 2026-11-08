import asyncio
import json
import logging
import os
import re
import threading

from engine.config.settings import DATA_DIR
from engine.observability.redact import redact_url
from engine.scraping.http_client import _is_safe_url, http_get, http_post
from engine.scraping.site.animessama import SEARCH_URL

log = logging.getLogger("engine.scraping.search")

_RE_FICHE = re.compile(r"(.*?/catalogue/[^/?#]+)", re.I)

def _fiche_url(url: str) -> str:
    m = _RE_FICHE.match(url or "")
    return m.group(1) if m else (url or "")

SEARCH_MAX_LEN = 200

_types_cache: dict[str, str] = {}
_types_cache_lock = threading.Lock()
# v6 : detecter_type_contenu lit les appels executes, plus le HTML brut ; la v5
# classait chaque fiche « both ». Changer le nom a chaque changement de verdict,
# sinon les types deja connus ne seraient jamais redemandes.
_TYPES_FILE = DATA_DIR / "scan_types_v6.json"
_TYPES_PERIMES = ("scan_types_v5.json",)
_TYPES_MAX = 5000
_types_loaded = False

def _load_types_cache() -> None:
    global _types_loaded
    with _types_cache_lock:
        if _types_loaded:
            return
        _types_loaded = True
        for nom in _TYPES_PERIMES:
            try:
                (_TYPES_FILE.parent / nom).unlink(missing_ok=True)
            except OSError as e:
                log.debug(f"scan_types perime {nom}: {e}")
        try:
            if _TYPES_FILE.exists():
                with open(_TYPES_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if v in ("scan", "anime", "both"):
                            _types_cache[k] = v
        except (OSError, json.JSONDecodeError) as e:
            log.debug(f"scan_types load: {e}")

def _save_types_cache() -> None:
    try:
        with _types_cache_lock:
            snapshot = dict(list(_types_cache.items())[-_TYPES_MAX:])
            tmp = _TYPES_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f)
            os.replace(tmp, _TYPES_FILE)
    except OSError as e:
        log.debug(f"scan_types save: {e}")

async def search_async(q: str, known_covers: dict | None = None) -> list[dict]:
    from engine.auth.manager import auth_manager
    from engine.scraping.parser import parse_search_results

    if not q or not q.strip():
        return []

    q = q.strip()

    if len(q) > SEARCH_MAX_LEN:
        log.debug(f"search_async : requête tronquée ({len(q)} → {SEARCH_MAX_LEN} caractères)")
        q = q[:SEARCH_MAX_LEN]

    try:
        r = await http_post(SEARCH_URL, auth_manager.cookies, {"query": q})
        if not r:
            log.warning(f"search_async : pas de réponse pour '{q[:40]}'")
            return []

        results = await asyncio.to_thread(parse_search_results, r.text)

        if known_covers and isinstance(known_covers, dict):
            for anime in results:
                if not anime.get("image"):
                    nom = anime.get("nom", "")
                    anime["image"] = known_covers.get(nom, "")

        log.debug(f"search_async '{q[:40]}' : {len(results)} résultats")
        return results

    except Exception as e:
        log.error(f"search_async : {e}", exc_info=True)
        return []

async def detecter_types_favoris_async(urls: list[str], max_parallele: int = 12) -> dict:
    from engine.auth.manager import auth_manager
    from engine.scraping.parser import detecter_type_contenu

    if not urls:
        return {}

    await asyncio.to_thread(_load_types_cache)

    a_faire: list[str] = []
    resultat: dict[str, str] = {}

    with _types_cache_lock:
        for u in urls:
            if not isinstance(u, str) or not u:
                continue
            if u in _types_cache:
                resultat[u] = _types_cache[u]
            elif _is_safe_url(u):
                a_faire.append(u)

    if not a_faire:
        return resultat

    sem = asyncio.Semaphore(max(1, min(max_parallele, 16)))

    async def _un(url: str):
        async with sem:
            try:
                r = await http_get(_fiche_url(url), auth_manager.cookies)
                if not r:
                    return url, None
                info = detecter_type_contenu(r.text)
                hs, ha = bool(info.get("has_scan")), bool(info.get("has_anime"))
                if ha:
                    return url, "both" if hs else "anime"
                if hs:
                    return url, "scan"
                return url, None
            except Exception as e:
                log.debug(f"detecter_types_favoris : {redact_url(url, 50)} → {e}")
                return url, None

    paires = await asyncio.gather(*[_un(u) for u in a_faire])

    with _types_cache_lock:
        for url, type_contenu in paires:
            if type_contenu is None:
                continue
            _types_cache[url] = type_contenu
            resultat[url] = type_contenu
        if len(_types_cache) > _TYPES_MAX:
            for k in list(_types_cache)[: len(_types_cache) - _TYPES_MAX]:
                _types_cache.pop(k, None)

    await asyncio.to_thread(_save_types_cache)
    log.debug(f"detecter_types_favoris : {len(paires)} fiches analysées "
              f"({sum(1 for _, t in paires if t == 'scan')} scans)")
    return resultat
