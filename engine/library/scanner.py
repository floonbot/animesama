import logging
import os
import time
from pathlib import Path

from engine.cache.ttl_cache import TTLCache
from engine.config.settings import VIDEO_EXTENSIONS

log = logging.getLogger("engine.library.scanner")

LIBRAIRIE_MAX_ANIMES = 1000
_DOSSIERS_CACHE_TTL = 120.0
_LIBRAIRIE_CACHE_TTL = 180.0

_dossiers_cache = TTLCache(_DOSSIERS_CACHE_TTL, "dossiers")
_librairie_cache = TTLCache(_LIBRAIRIE_CACHE_TTL, "librairie")

def invalider_cache_dossiers() -> None:
    _dossiers_cache.invalidate()

def dossiers_actifs() -> list[Path]:
    tc = _dossiers_cache
    cached = tc.get()
    if cached is not None:
        return cached

    from engine.config.settings import get_downloads_dir, get_scans_dir

    dossiers: list[Path] = []
    seen: set[str] = set()
    for getter, label in ((get_downloads_dir, "download"), (get_scans_dir, "scans")):
        d = getter()
        try:
            p = d.resolve()
        except (OSError, ValueError):
            p = d
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if p.exists():
            dossiers.append(p)
        else:
            log.warning("%s directory not found: %s", label, p)

    if not dossiers:
        log.error("no valid download/scans directory found")
        return dossiers

    tc.set(dossiers)
    return dossiers

def est_dans_downloads(fichier: str) -> bool:
    if not fichier or not isinstance(fichier, str):
        return False
    try:
        cible = Path(fichier).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    for d in dossiers_actifs():
        try:
            base = d.resolve()
        except (OSError, ValueError, RuntimeError):
            continue
        if cible == base or base in cible.parents:
            return True
    return False

def _scan_un_dossier(racine: Path) -> tuple[dict[str, dict], bool]:
    import stat as _stat

    animes_par_nom: dict[str, dict] = {}
    tronque = False

    try:
        if not racine.exists():
            return animes_par_nom, False
        anime_dirs = sorted(racine.iterdir())
    except (OSError, PermissionError):
        log.error("read %s failed", racine, exc_info=True)
        return animes_par_nom, False

    for anime_dir in anime_dirs:
        if len(animes_par_nom) >= LIBRAIRIE_MAX_ANIMES:
            tronque = True
            break
        try:
            if not anime_dir.is_dir() or anime_dir.name.startswith("_"):
                continue
        except OSError:
            continue

        saisons: list[dict] = []
        total_eps = 0
        total_size = 0

        try:
            saison_entries = sorted(os.scandir(anime_dir), key=lambda e: e.name)
        except (OSError, PermissionError):
            continue

        for saison_entry in saison_entries:
            try:
                if not saison_entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue

            episodes: list[dict] = []
            try:
                file_entries = sorted(os.scandir(saison_entry.path), key=lambda e: e.name)
            except (OSError, PermissionError):
                continue

            for fe in file_entries:
                name_low = fe.name.lower()
                is_video = name_low.endswith(VIDEO_EXTENSIONS)
                is_scan = name_low.endswith(".cbz")
                if not (is_video or is_scan):
                    continue
                try:
                    st = fe.stat()
                    if not _stat.S_ISREG(st.st_mode):
                        continue
                except OSError:
                    continue

                size = st.st_size
                total_size += size
                total_eps += 1
                stem = fe.name.rsplit(".", 1)[0]
                ep = {
                    "nom": stem,
                    "fichier": fe.path,
                    "taille": round(size / 1024 / 1024, 1),
                    "mtime": int(st.st_mtime),
                }
                if is_scan:
                    ep["scan"] = True
                episodes.append(ep)
            if episodes:
                saisons.append({"nom": saison_entry.name, "episodes": episodes})

        if saisons:
            animes_par_nom[anime_dir.name] = {
                "nom": anime_dir.name,
                "saisons": saisons,
                "total_eps": total_eps,
                "total_size_bytes": total_size,
            }

    return animes_par_nom, tronque

def _cle_fusion(nom: str) -> str:
    return "".join(ch for ch in nom.lower() if ch.isalnum()) or nom.lower()

def scan_librairie_sync() -> dict:
    t0 = time.time()
    fusion: dict[str, dict] = {}
    tronque = False

    for racine in dossiers_actifs():
        animes_un, tr_un = _scan_un_dossier(racine)
        if tr_un:
            tronque = True
        for nom, donnees in animes_un.items():
            cle = _cle_fusion(nom)
            if cle in fusion:
                existant = fusion[cle]
                saisons_existantes = {s["nom"] for s in existant["saisons"]}
                for s in donnees["saisons"]:
                    if s["nom"] not in saisons_existantes:
                        existant["saisons"].append(s)
                        saisons_existantes.add(s["nom"])
                    else:
                        cible = next(x for x in existant["saisons"] if x["nom"] == s["nom"])
                        connus = {e["fichier"] for e in cible["episodes"]}
                        for e in s["episodes"]:
                            if e["fichier"] not in connus:
                                cible["episodes"].append(e)
                                connus.add(e["fichier"])
                existant["total_eps"] += donnees["total_eps"]
                existant["total_size_bytes"] += donnees["total_size_bytes"]
            else:
                fusion[cle] = donnees

    animes: list[dict] = []
    for donnees in fusion.values():
        donnees["saisons"].sort(key=lambda s: s["nom"])
        donnees["total_size"] = round(donnees.pop("total_size_bytes") / 1024 / 1024 / 1024, 2)
        animes.append(donnees)

    log.debug("library scan done in %.2fs — %d animes", time.time() - t0, len(animes))
    return {"animes": animes, "total": len(animes), "tronque": tronque}

def invalider_cache_librairie() -> None:
    _librairie_cache.invalidate()

def librairie_cache_get() -> dict | None:
    return _librairie_cache.get()

def librairie_cache_set(result: dict) -> None:
    _librairie_cache.set(result)
