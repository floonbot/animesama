import logging

from fastapi import APIRouter

from engine.library.coherence import verifier_coherence_librairie
from engine.library.updates import check_updates_async

router = APIRouter()
log    = logging.getLogger("web.api.updates")

@router.get("/check-updates")
async def check_updates(refresh: bool = False):
    try:
        return await check_updates_async(refresh)
    except Exception:
        log.error("check_updates failed", exc_info=True)
        return {"animes": [], "total_nouveaux": 0, "erreur": True}

@router.get("/coherence-librairie")
async def coherence_librairie():
    try:
        return await verifier_coherence_librairie()
    except Exception:
        log.error("coherence_librairie failed", exc_info=True)
        return {"incoherents": [], "total": 0, "verifies": 0, "matched": 0, "erreur": True}
