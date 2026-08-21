
import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from engine.services.download_service import download_service

router = APIRouter()
log    = logging.getLogger("web.api.download")

EPISODES_MAX_PAR_LOT = 500

class DlEpisodeBody(BaseModel):
    ep:       dict
    episodes: list[dict] = Field(default_factory=list, max_length=EPISODES_MAX_PAR_LOT)

class DlDirectBody(BaseModel):
    url:         str  = Field(..., min_length=10, max_length=2000)
    headers:     dict = Field(default_factory=dict)
    nom_fichier: str  = Field("", max_length=200)

class DeplacerBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: int = Field(0, alias="from")
    to:    int = 0

SCAN_MAX_CHAPITRES = 5000

class DlScanBody(BaseModel):
    slug:      str  = Field(..., min_length=1, max_length=200)
    oeuvre:    str  = Field(..., min_length=1, max_length=200)
    lang:      str  = Field("vf", max_length=4)
    chapitres: list = Field(default_factory=list, max_length=SCAN_MAX_CHAPITRES)
    nom:       str  = Field("", max_length=200)

@router.get("/status")
async def get_status():
    try:
        return download_service.statut()
    except Exception as e:
        log.error(f"get_status : {e}")
        return {"en_cours": None, "queue": [], "historique": [], "elapsed": 0, "en_pause": False}

@router.post("/episode")
async def dl_episode(body: DlEpisodeBody):
    try:
        if not isinstance(body.ep, dict):
            return {"ok": False, "message": "ep manquant ou invalide"}
        eps = body.episodes if body.episodes else [body.ep]
        eps = [e for e in eps if isinstance(e, dict)]
        if not eps:
            return {"ok": False, "message": "Aucun épisode valide"}

        item = {"ep": body.ep, "episodes": eps}
        return await download_service.ajouter_episode(item)
    except Exception as e:
        log.error(f"dl_episode : {e}")
        return {"ok": False, "message": "Erreur ajout queue"}

@router.post("/direct")
async def dl_direct(body: DlDirectBody):
    try:
        return await download_service.ajouter_direct(
            body.url, body.nom_fichier, body.headers
        )
    except Exception as e:
        log.error(f"dl_direct : {e}")
        return {"ok": False, "message": "Erreur ajout queue"}

@router.post("/scan")
async def dl_scan(body: DlScanBody):
    try:
        chapitres = [str(c) for c in body.chapitres if str(c).strip()][:SCAN_MAX_CHAPITRES]
        if not chapitres:
            return {"ok": False, "message": "Aucun chapitre sélectionné"}
        return await download_service.ajouter_scan(
            body.slug, body.oeuvre, body.lang, chapitres, body.nom
        )
    except Exception as e:
        log.error(f"dl_scan : {e}")
        return {"ok": False, "message": "Erreur ajout queue"}

@router.post("/annuler")
async def annuler():
    try:
        return await asyncio.to_thread(download_service.annuler)
    except Exception as e:
        log.error(f"annuler : {e}")
        return {"ok": False}

@router.post("/pause")
async def pause():
    try:
        return download_service.pause()
    except Exception as e:
        log.error(f"pause : {e}")
        return {"ok": False, "en_pause": False}

@router.post("/reprendre")
async def reprendre():
    try:
        return download_service.reprendre()
    except Exception as e:
        log.error(f"reprendre : {e}")
        return {"ok": False, "en_pause": False}

@router.post("/historique/clear")
async def vider_historique():
    try:
        return download_service.vider_historique()
    except Exception as e:
        log.error(f"vider_historique : {e}")
        return {"ok": False}

@router.delete("/queue/{index}")
async def retirer(index: int):
    try:
        return {"ok": download_service.retirer(index)}
    except Exception as e:
        log.error(f"retirer : {e}")
        return {"ok": False}

@router.post("/deplacer")
async def deplacer(body: DeplacerBody):
    try:
        ok = download_service.deplacer(body.from_, body.to)
        return {"ok": ok}
    except Exception as e:
        log.error(f"deplacer : {e}")
        return {"ok": False}

@router.get("/breakers")
async def etat_circuit_breakers():
    try:
        return {"ok": True, "breakers": download_service.etat_breakers()}
    except Exception as e:
        log.error(f"etat_circuit_breakers : {e}")
        return {"ok": False, "breakers": {}}

@router.get("/metrics")
async def metriques():
    try:
        from engine.download.extractor.registry import canonical_host, supported_hosts
        from engine.observability.metrics import metrics
        resume = metrics.resume_detaille(
            supported_hosts=supported_hosts, canonical_host=canonical_host
        )
        try:
            resume["queue_depth"] = len(download_service.statut().get("queue", []))
        except Exception:
            log.debug("metrics queue_depth", exc_info=True)
        return {
            "ok": True,
            "metrics": metrics.snapshot(),
            "gauges": metrics.gauges(),
            "resume": resume,
        }
    except Exception as e:
        log.error(f"metrics : {e}")
        return {"ok": False, "metrics": {}}
