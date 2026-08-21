import asyncio
import json
import logging

from fastapi import APIRouter, Response

from engine.library import scanner
from engine.utils.aio import loop_local_lock

router = APIRouter()
log = logging.getLogger("web.api.anime")

_lib_scan_lock = loop_local_lock()

# Rendre le dict tel quel faisait repasser toute la librairie dans
# jsonable_encoder (18 ms pour 120 animes) puis json.dumps (2,5 ms), a chaque
# requete, alors que le contenu ne bouge pas de tout le TTL du cache.
# Le memo compare l'objet par identite : le scanner remplace le dict entier
# quand il rafraichit, donc un `is` qui echoue *est* l'invalidation — il n'y a
# pas de second cache a tenir synchronise. Un seul creneau : deux profils
# interroges en alternance re-serialisent, cas sans interet en pratique.
_serialise: tuple[dict, bytes] | None = None


def _encoder(donnees: dict) -> bytes:
    return json.dumps(donnees, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _payload_json(donnees: dict) -> bytes:
    global _serialise
    memo = _serialise
    if memo is not None and memo[0] is donnees:
        return memo[1]
    brut = _encoder(donnees)
    _serialise = (donnees, brut)
    return brut


def _reponse(donnees: dict) -> Response:
    return Response(content=_payload_json(donnees), media_type="application/json")

@router.get("/librairie")
async def get_librairie():
    cached = scanner.librairie_cache_get()
    if cached is not None:
        return _reponse(cached)
    async with _lib_scan_lock.require():
        cached = scanner.librairie_cache_get()
        if cached is not None:
            return _reponse(cached)
        try:
            result = await asyncio.to_thread(scanner.scan_librairie_sync)
        except Exception:
            log.error("get_librairie failed", exc_info=True)
            return {"animes": [], "total": 0, "tronque": False}
        scanner.librairie_cache_set(result)
        return _reponse(result)
