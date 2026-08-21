import logging
import os
import shutil
from typing import Any

from engine.config.settings import VIDEO_EXTENSIONS

log = logging.getLogger("engine.download.helpers")

TAILLE_MIN_FICHIER = 10 * 1024 * 1024
ESPACE_DISQUE_MIN_MB = 500

def _coerce_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

def normaliser_episodes(item: dict) -> list[dict]:
    eps = item.get("episodes") or ([item["ep"]] if "ep" in item else [])
    eps = [e for e in eps if isinstance(e, dict)]
    if not eps:
        return []
    ref0 = eps[0].get("titre") or eps[0].get("nom")
    titre_ref = ref0 if isinstance(ref0, str) and ref0 else "Anime"
    for e in eps:
        t = e.get("titre")
        if not (isinstance(t, str) and t):
            e["titre"] = titre_ref
        e["saison"] = _coerce_int(e.get("saison"), 1) or 1
        e["episode"] = _coerce_int(e.get("episode"), 0)
    return eps

def skip_existants_actif() -> bool:
    try:
        from engine.config.user_settings import load_settings
        return load_settings().get("skip_existants", True) is not False
    except Exception:
        return True

def espace_disque_suffisant(dossier: str, minimum_mb: int = ESPACE_DISQUE_MIN_MB) -> bool:
    try:
        p = dossier
        while p and not os.path.isdir(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        if not p or not os.path.isdir(p):
            return True
        libre_mb = shutil.disk_usage(p).free // (1024 * 1024)
        if libre_mb < minimum_mb:
            log.warning("low disk space: %d MB free (< %d MB)", libre_mb, minimum_mb)
            return False
        return True
    except Exception:
        return True

def fichier_existe(dossier: str, nom: str) -> str | None:
    from engine.download._engine_utils import borner_nom_fichier

    # Les moteurs ecrivent sous borner_nom_fichier(dossier, nom, ".mp4") : chercher
    # le nom complet uniquement rendrait skip_existants aveugle aux titres longs.
    noms = [nom]
    borne = borner_nom_fichier(dossier, nom, ".mp4", silencieux=True)
    if borne != nom:
        noms.append(borne)
    try:
        if not os.path.exists(dossier):
            return None
        if any(os.path.isdir(os.path.join(dossier, "_tmp_" + n)) for n in noms):
            return None
    except OSError:
        return None
    for n in noms:
        for ext in VIDEO_EXTENSIONS:
            chemin = os.path.join(dossier, n + ext)
            try:
                if os.path.exists(chemin) and os.path.getsize(chemin) > TAILLE_MIN_FICHIER:
                    return chemin
            except OSError:
                continue
    return None
