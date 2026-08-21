import asyncio
import logging
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from engine.library import scanner
from engine.library.updates import invalider_cache_updates
from web.api.routes.anime._models import FichierBody

router = APIRouter()
log = logging.getLogger("web.api.anime")

_SCAN_IMG_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif",
}

def _cbz_names(zf) -> list[str]:
    names = [n for n in zf.namelist()
             if Path(n).suffix.lower() in _SCAN_IMG_TYPES]
    names.sort()
    return names

def _cbz_pages(fichier: str) -> list[str]:
    with zipfile.ZipFile(fichier) as zf:
        return _cbz_names(zf)

def _open_in_file_manager(dossier: str) -> None:
    if sys.platform == "win32":
        os.startfile(dossier)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", dossier])
    else:
        subprocess.Popen(["xdg-open", dossier])

_VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".ts": "video/mp2t",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
}

def _chemin_invalide(fichier: str) -> dict | None:
    if not scanner.est_dans_downloads(fichier):
        return {"ok": False, "message": "Chemin non autorisé"}
    if not os.path.exists(fichier):
        return {"ok": False, "message": "Fichier introuvable"}
    return None

@router.post("/ouvrir-dossier")
async def ouvrir_dossier(body: FichierBody):
    fichier = body.fichier.strip()
    err = _chemin_invalide(fichier)
    if err:
        return err
    try:
        dossier = os.path.dirname(os.path.abspath(fichier))
        await asyncio.to_thread(_open_in_file_manager, dossier)
        return {"ok": True}
    except Exception:
        log.error("ouvrir_dossier failed", exc_info=True)
        return {"ok": False, "message": "Impossible d'ouvrir le dossier"}

@router.post("/supprimer")
async def supprimer_episode(body: FichierBody):
    fichier = body.fichier.strip()
    if Path(fichier).suffix.lower() not in _VIDEO_MEDIA_TYPES and Path(fichier).suffix.lower() != ".cbz":
        return {"ok": False, "message": "Type de fichier non autorisé"}
    err = _chemin_invalide(fichier)
    if err:
        return err
    try:
        await asyncio.to_thread(os.remove, fichier)
        log.info("file deleted: %s", os.path.basename(fichier))
        scanner.invalider_cache_librairie()
        invalider_cache_updates()
        return {"ok": True}
    except (OSError, PermissionError):
        log.error("delete failed", exc_info=True)
        return {"ok": False, "message": "Suppression impossible"}

@router.get("/stream")
async def stream_video(fichier: str = Query(..., min_length=1, max_length=2000)):
    if Path(fichier).suffix.lower() not in _VIDEO_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Type de fichier non autorisé")
    if not scanner.est_dans_downloads(fichier):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")
    if not os.path.exists(fichier):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    if not os.path.isfile(fichier):
        raise HTTPException(status_code=400, detail="Pas un fichier")
    media_type = _VIDEO_MEDIA_TYPES.get(Path(fichier).suffix.lower(), "application/octet-stream")
    return FileResponse(fichier, media_type=media_type, headers={"Accept-Ranges": "bytes"})

def _valider_cbz(fichier: str) -> None:
    if Path(fichier).suffix.lower() != ".cbz":
        raise HTTPException(status_code=400, detail="Pas un fichier .cbz")
    if not scanner.est_dans_downloads(fichier):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")
    if not os.path.isfile(fichier):
        raise HTTPException(status_code=404, detail="Fichier introuvable")

@router.get("/scan-local")
async def scan_local(fichier: str = Query(..., min_length=1, max_length=2000)):
    _valider_cbz(fichier)
    try:
        pages = await asyncio.to_thread(_cbz_pages, fichier)
    except (zipfile.BadZipFile, OSError):
        raise HTTPException(status_code=400, detail="CBZ illisible") from None
    return {"ok": True, "pages": len(pages), "nom": Path(fichier).stem}

@router.get("/scan-local-img")
async def scan_local_img(
    fichier: str = Query(..., min_length=1, max_length=2000),
    page: int = Query(..., ge=0, le=10000),
):
    _valider_cbz(fichier)

    def _lire() -> tuple[bytes, str]:
        with zipfile.ZipFile(fichier) as zf:
            names = _cbz_names(zf)
            if page >= len(names):
                raise HTTPException(status_code=404, detail="Page hors limites")
            return zf.read(names[page]), Path(names[page]).suffix.lower()

    try:
        data, ext = await asyncio.to_thread(_lire)
    except HTTPException:
        raise
    except (zipfile.BadZipFile, OSError, KeyError):
        raise HTTPException(status_code=400, detail="Lecture CBZ impossible") from None
    return Response(content=data, media_type=_SCAN_IMG_TYPES.get(ext, "application/octet-stream"),
                    headers={"Cache-Control": "public, max-age=86400"})
