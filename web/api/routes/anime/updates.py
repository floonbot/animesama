import asyncio
import logging

from fastapi import APIRouter

from engine.library import sante
from engine.library.coherence import verifier_coherence_librairie
from engine.library.updates import check_updates_async
from web.api.routes.anime._models import SanteReparerBody

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

@router.get("/sante-librairie")
async def sante_librairie():
    try:
        return await asyncio.to_thread(sante.analyser)
    except Exception:
        log.error("sante_librairie failed", exc_info=True)
        return {"problemes": [], "fichiers": 0, "duree_s": 0, "dossiers": [], "erreur": True}

@router.get("/sante-librairie/etat")
async def sante_librairie_etat():
    return sante.etat()

@router.post("/sante-librairie/reparer")
async def sante_librairie_reparer(body: SanteReparerBody):
    return sante.demarrer_reparation(body.chemins)

@router.post("/sante-librairie/annuler")
async def sante_librairie_annuler():
    sante.annuler_reparation()
    return {"ok": True}
