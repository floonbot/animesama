import asyncio
import logging
import math
import threading
import time

from fastapi import APIRouter, HTTPException

from engine.utils.aio import loop_local_semaphore
from web.api.models import AuthStatus, LoginRequest

router = APIRouter()
log    = logging.getLogger("web.api.auth")

_login_sem = loop_local_semaphore(1)

_last_login_ts: float = 0.0
_last_login_lock = threading.Lock()
_MIN_DELAI_LOGINS = 1.0
_MAX_WAIT_LOGIN   = 5.0

def _login_semaphore() -> asyncio.Semaphore | None:
    return _login_sem.get()

@router.get("/status", response_model=AuthStatus)
async def get_status():
    try:
        from engine.auth.manager import auth_manager
        return AuthStatus(connected=auth_manager.is_logged_in, username=auth_manager.username)
    except Exception as e:
        log.error(f"get_status : {e}")
        return AuthStatus(connected=False, username=None)

@router.post("/login")
async def login(body: LoginRequest):
    global _last_login_ts

    with _last_login_lock:
        now    = time.time()
        delta  = now - _last_login_ts
        wait_s = max(0.0, _MIN_DELAI_LOGINS - delta)
        if wait_s >= _MAX_WAIT_LOGIN:
            # Chaque appel reserve un creneau d'une seconde en avancant
            # _last_login_ts : la file se vide donc dans wait_s - _MIN_DELAI_LOGINS,
            # pas dans wait_s. Le refus n'ajoute rien a la file, il la laisse
            # s'ecouler — annoncer « quelques secondes » n'aidait personne.
            reste = max(1, math.ceil(wait_s - _MIN_DELAI_LOGINS))
            log.warning(f"login refusé (file trop longue, wait={wait_s:.1f}s, reste={reste}s)")
            raise HTTPException(
                status_code=429,
                detail=f"Trop de tentatives rapprochées — réessaie dans {reste} s",
                headers={"Retry-After": str(reste)},
            )
        _last_login_ts = now + wait_s

    if wait_s > 0:
        try:
            await asyncio.sleep(wait_s)
        except asyncio.CancelledError:
            raise

    try:
        sem = _login_semaphore()
        if sem is None:
            log.error("login : impossible d'obtenir le sémaphore asyncio")
            return {"ok": False, "message": "Erreur interne (loop asyncio)"}
        async with sem:
            from engine.auth.manager import auth_manager
            return await auth_manager.login_async(body.pseudo, body.password)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"login : {e}")
        return {"ok": False, "message": "Erreur interne pendant le login"}

@router.post("/logout")
async def logout():
    try:
        from engine.auth.manager import auth_manager
        await asyncio.to_thread(auth_manager.logout)
        return {"ok": True}
    except Exception as e:
        log.error(f"logout : {e}")
        return {"ok": False, "message": "Erreur pendant la déconnexion"}
