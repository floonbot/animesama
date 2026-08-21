import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse

from engine.cache.covers import (
    COVERS_MAX_ENTRIES,
    _covers_cache,
    _covers_lock_thread,
    _save_covers,
)
from engine.utils.aio import loop_local_lock
from engine.utils.security import is_safe_url
from web.api.routes.anime._models import CoversBody

router = APIRouter()
log = logging.getLogger("web.api.anime")

_covers_lock_ll = loop_local_lock()

def _covers_lock() -> asyncio.Lock:
    return _covers_lock_ll.require()

@router.get("/cover")
async def cover_proxy(u: str = Query(..., min_length=10, max_length=2000)):
    if not await asyncio.to_thread(is_safe_url, u):
        raise HTTPException(status_code=400, detail="URL invalide")
    from engine.cache.cover_images import cached_file, warm

    path = cached_file(u)
    if path is not None:
        return FileResponse(
            str(path),
            headers={"Cache-Control": "public, max-age=2592000, immutable"},
        )
    warm(u)
    return RedirectResponse(u, status_code=307)

@router.get("/covers")
async def get_covers():
    with _covers_lock_thread:
        return dict(_covers_cache)

@router.post("/covers")
async def update_covers(body: CoversBody):
    covers = body.covers
    if not isinstance(covers, dict):
        return {"ok": False, "message": "Format invalide"}
    if len(covers) > COVERS_MAX_ENTRIES:
        return {"ok": False, "message": f"Trop d'entrées (max {COVERS_MAX_ENTRIES})"}

    propres: dict[str, str] = {}
    for k, v in covers.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        if len(k) > 200 or len(v) > 500:
            continue
        v_low = v.lower()
        if not (v_low.startswith("http://") or v_low.startswith("https://") or v_low.startswith("data:")):
            continue
        propres[k] = v

    with _covers_lock_thread:
        nouveaux = {k: v for k, v in propres.items() if _covers_cache.get(k) != v}
        if not nouveaux:
            return {"ok": True, "total": len(_covers_cache), "ajoutes": 0}

    async with _covers_lock():
        with _covers_lock_thread:
            _covers_cache.update(nouveaux)
            if len(_covers_cache) > COVERS_MAX_ENTRIES:
                items = list(_covers_cache.items())[-COVERS_MAX_ENTRIES:]
                _covers_cache.clear()
                _covers_cache.update(dict(items))
                log.warning("covers cache truncated to %d", COVERS_MAX_ENTRIES)
            snapshot = dict(_covers_cache)
        ok = await asyncio.to_thread(_save_covers, snapshot)
        if not ok:
            log.warning("disk save failed — RAM cache updated anyway")
    return {"ok": True, "total": len(snapshot), "ajoutes": len(nouveaux)}
