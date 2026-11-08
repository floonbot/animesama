import logging

from fastapi import APIRouter, HTTPException, Query

from engine.cache.covers import _covers_cache, _covers_lock_thread
from engine.scraping.scraper import is_site_url as _est_url_site
from web.api.routes.anime._models import TypesFavorisBody

router = APIRouter()
log = logging.getLogger("web.api.anime")

@router.get("/favoris")
async def get_favoris(refresh: bool = False):
    try:
        from engine.scraping.scraper import get_favorites_async, invalidate_fav_cache
        if refresh:
            await invalidate_fav_cache()
        animes = await get_favorites_async(force_refresh=refresh)
        return {"animes": animes or []}
    except Exception:
        log.error("get_favoris failed", exc_info=True)
        return {"animes": []}

@router.post("/types-favoris")
async def types_favoris(body: TypesFavorisBody):
    urls = [u for u in (body.urls or []) if isinstance(u, str)][:400]
    if not urls:
        return {"types": {}}
    try:
        from engine.scraping.scraper import detecter_types_favoris_async
        types = await detecter_types_favoris_async(urls)
        return {"types": types}
    except Exception:
        log.error("types_favoris failed", exc_info=True)
        return {"types": {}}

@router.get("/episodes")
async def get_episodes(url: str = Query(..., min_length=10, max_length=500)):
    if not _est_url_site(url):
        raise HTTPException(status_code=400, detail="URL non autorisée")
    try:
        from engine.scraping.scraper import get_episodes_async
        return await get_episodes_async(url)
    except Exception:
        log.error("get_episodes failed", exc_info=True)
        return {"titre": "", "episodes": [], "langues": [], "total": 0}

@router.get("/synopsis")
async def synopsis(
    url: str = Query("", max_length=500),
    nom: str = Query("", max_length=300),
):
    """Par l'URL de la fiche (favoris), ou par le nom de dossier (librairie)."""
    from engine.scraping.synopsis import get_synopsis_async, url_pour_nom

    if url:
        if not _est_url_site(url):
            raise HTTPException(status_code=400, detail="URL non autorisée")
    elif nom.strip():
        try:
            url = await url_pour_nom(nom.strip())
        except Exception:
            log.debug("synopsis : fiche introuvable pour %s", nom[:60], exc_info=True)
            url = ""
        if not url:
            return {"synopsis": "", "url": ""}
    else:
        raise HTTPException(status_code=400, detail="url ou nom requis")
    try:
        return {"synopsis": await get_synopsis_async(url), "url": url}
    except Exception:
        log.error("synopsis failed", exc_info=True)
        return {"synopsis": "", "url": url}

@router.get("/scan")
async def scan_chapitres(
    slug: str = Query(..., min_length=1, max_length=200),
    lang: str = Query("vf", max_length=4),
):
    from engine.scraping.scraper import get_scan_info, slug_valide
    if not slug_valide(slug):
        raise HTTPException(status_code=400, detail="Slug invalide")
    try:
        return await get_scan_info(slug, lang)
    except Exception:
        log.error("scan_chapitres failed", exc_info=True)
        return {"ok": False, "error": "Erreur scan", "chapitres": []}

@router.get("/scan-pages")
async def scan_pages(
    oeuvre: str = Query(..., min_length=1, max_length=200),
    chap: str = Query(..., min_length=1, max_length=20),
    lang: str = Query("vf", max_length=4),
):
    from engine.scraping.scraper import get_pages
    try:
        return {"pages": await get_pages(oeuvre, chap, lang)}
    except Exception:
        log.error("scan_pages failed", exc_info=True)
        return {"pages": []}

@router.get("/recherche")
async def recherche(q: str = Query(..., min_length=1, max_length=100)):
    try:
        from engine.scraping.scraper import search_async
        with _covers_lock_thread:
            snapshot = dict(_covers_cache)
        results = await search_async(q, known_covers=snapshot)
        return {"animes": results, "total": len(results)}
    except Exception:
        log.error("recherche failed", exc_info=True)
        return {"animes": [], "total": 0}

@router.get("/catalogue")
async def catalogue(
    genre: str = Query("", max_length=60),
    type: str = Query("", max_length=20),
    langue: str = Query("", max_length=10),
    statut: str = Query("", max_length=20),
    page: int = Query(1, ge=1, le=200),
):
    try:
        from engine.scraping.scraper import catalogue_async
        results = await catalogue_async(genre=genre, type_=type, langue=langue, statut=statut, page=page)
        return {"animes": results, "total": len(results), "page": page}
    except Exception:
        log.error("catalogue failed", exc_info=True)
        return {"animes": [], "total": 0, "page": page}

@router.get("/catalogue-genres")
async def catalogue_genres():
    try:
        from engine.scraping.scraper import catalogue_genres_async
        return {"genres": await catalogue_genres_async()}
    except Exception:
        log.error("catalogue-genres failed", exc_info=True)
        return {"genres": []}
