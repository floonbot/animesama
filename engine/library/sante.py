"""Controle de sante de la librairie : ce que le lecteur integre ne lira pas.

Mesure du 07/11/2026 sur la librairie de l'utilisateur (1693 MP4) : 190 sont des
flux MPEG-TS bruts sous une extension .mp4 (ecrits du 13 au 25/07 par un ancien
moteur) et 4 sont tronques. Le lecteur de l'app est un <video> Chromium : il ne
lit pas le MPEG-TS. Un remux sans reencodage les repare (3 s pour 890 Mo en
local, duree identique au centieme).

On ne parcourt que ce que la librairie affiche (racine/oeuvre/saison/fichier),
et un fichier modifie depuis moins d'une heure peut appartenir a un
telechargement en cours : il n'est ni signale ni touche.
"""

import logging
import os
import shutil
import stat
import subprocess
import threading
import time
from pathlib import Path

from engine.download._engine_utils import (
    NO_WINDOW_FLAGS,
    clean_subprocess_env,
    creer_dossier_de_travail,
    livrer,
    mp4_complet,
    supprimer_silencieux,
    terminate_tree,
)

log = logging.getLogger("engine.library.sante")

RECENT_S = 3600
_CONVERSION_TIMEOUT_S = 1800
# L'enveloppe TS coute 2 a 10 % ; une sortie bien plus petite a perdu un flux.
_RATIO_TAILLE_MIN = 0.8
_TS_PAQUET = 188
_RESIDUS = (".part", ".livraison", ".ytdl", ".aria2")

SUPPRIMER = "supprimer"
RENOMMER = "renommer"
CONVERTIR = "convertir"


def _est_flux_ts(chemin: str) -> bool:
    try:
        with open(chemin, "rb") as f:
            debut = f.read(2 * _TS_PAQUET + 1)
    except OSError:
        return False
    return len(debut) == 2 * _TS_PAQUET + 1 and all(
        debut[i] == 0x47 for i in (0, _TS_PAQUET, 2 * _TS_PAQUET)
    )


def _probleme(chemin: str, taille: int, type_: str, action: str, detail: str,
              cible: str | None = None) -> dict:
    p = Path(chemin)
    return {
        "chemin": chemin,
        "fichier": p.name,
        "saison": p.parent.name,
        "anime": p.parent.parent.name,
        "type": type_,
        "action": action,
        "cible": cible or chemin,
        "taille": taille,
        "detail": detail,
    }


def classer(chemin: str, maintenant: float | None = None) -> dict | None:
    """Le probleme de ce fichier, ou None s'il est sain (ou trop recent pour juger)."""
    try:
        st = os.stat(chemin)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    if (maintenant if maintenant is not None else time.time()) - st.st_mtime < RECENT_S:
        return None

    dossier, nom = os.path.split(chemin)
    bas = nom.lower()

    def _p(type_: str, action: str, detail: str, cible: str | None = None) -> dict:
        return _probleme(chemin, st.st_size, type_, action, detail, cible)

    if bas.endswith(_RESIDUS) or ".part-frag" in bas or bas.startswith(".remux_tmp_"):
        return _p("residu", SUPPRIMER, "Reste d'un téléchargement interrompu")

    for suffixe in (".mux.mp4", ".mux.mkv"):
        if bas.endswith(suffixe):
            final = os.path.join(dossier, nom[: -len(suffixe)] + ".mp4")
            if os.path.exists(final):
                return _p("residu", SUPPRIMER, "Doublon : l'épisode final existe déjà")
            if suffixe == ".mux.mp4" and mp4_complet(chemin):
                return _p("mux", RENOMMER, "Épisode complet jamais renommé (.MUX)", final)
            return _p("residu", SUPPRIMER, "Assemblage interrompu en route")

    if bas.endswith(".ts"):
        base = nom[:-3]
        if base.lower().endswith(".copy"):
            return _p("residu", SUPPRIMER, "Copie intermédiaire de N_m3u8DL-RE")
        final = os.path.join(dossier, base + ".mp4")
        if os.path.exists(final):
            # Un .mp4 abime a son propre diagnostic : ne pas l'ecraser d'ici.
            return _p("residu", SUPPRIMER, "Flux déjà converti en .mp4") if mp4_complet(final) else None
        return _p("ts", CONVERTIR, "Flux .ts, illisible dans l'app : conversion en .mp4", final)

    if bas.endswith((".mp4", ".m4v")):
        if mp4_complet(chemin):
            return None
        if _est_flux_ts(chemin):
            return _p("ts", CONVERTIR, "Flux MPEG-TS sous une extension .mp4 : illisible dans l'app")
        return _p("tronque", SUPPRIMER, "Fichier tronqué : la fin de la vidéo manque")
    return None


def _fichiers_de_la_librairie(racine: Path):
    try:
        oeuvres = [e for e in os.scandir(racine) if e.is_dir() and not e.name.startswith("_")]
    except OSError:
        log.warning("santé : lecture de %s impossible", racine, exc_info=True)
        return
    for oeuvre in oeuvres:
        try:
            saisons = [e for e in os.scandir(oeuvre.path) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for saison in saisons:
            try:
                fichiers = [e.path for e in os.scandir(saison.path) if e.is_file(follow_symlinks=False)]
            except OSError:
                continue
            yield from fichiers


def analyser() -> dict:
    from engine.library.scanner import dossiers_actifs

    t0 = time.time()
    maintenant = t0
    problemes: list[dict] = []
    vus = 0
    racines = dossiers_actifs()
    for racine in racines:
        for chemin in _fichiers_de_la_librairie(racine):
            vus += 1
            p = classer(chemin, maintenant)
            if p:
                problemes.append(p)
    problemes.sort(key=lambda p: (p["type"], p["anime"].lower(), p["saison"], p["fichier"]))
    duree = round(time.time() - t0, 1)
    log.info("santé de la librairie : %d problème(s) sur %d fichier(s) en %.1fs", len(problemes), vus, duree)
    return {
        "problemes": problemes,
        "fichiers": vus,
        "duree_s": duree,
        "dossiers": [str(r) for r in racines],
    }


# ── Reparation : un fil, un fichier a la fois, annulable ─────────────────────

_verrou = threading.Lock()
_annulation = threading.Event()
_proc: subprocess.Popen | None = None
_etat: dict = {"en_cours": False, "total": 0, "faits": 0, "reussis": 0,
               "courant": "", "echecs": [], "annule": False, "termine_a": 0}


def etat() -> dict:
    with _verrou:
        return {**_etat, "echecs": list(_etat["echecs"])}


def _convertir(source: str, cible: str) -> tuple[bool, str]:
    global _proc
    from engine.download.methods.nm3u8dl import _find_ffmpeg

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg introuvable"
    st = os.stat(source)
    travail = None
    try:
        # Ecrire en local puis livrer : sur le NAS, la reecriture faststart echoue.
        travail = creer_dossier_de_travail()
        sortie = os.path.join(travail, "video.mp4")
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-fflags", "+genpts+igndts", "-i", source, "-c", "copy",
               "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", sortie]
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, env=clean_subprocess_env(),
                                creationflags=NO_WINDOW_FLAGS)
        with _verrou:
            _proc = proc
        if _annulation.is_set():
            terminate_tree(proc)
        try:
            _, err = proc.communicate(timeout=_CONVERSION_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            terminate_tree(proc)
            proc.communicate()
            return False, "Conversion trop longue, abandonnée"
        finally:
            with _verrou:
                _proc = None
        if _annulation.is_set():
            return False, "Annulé"
        if proc.returncode != 0:
            ligne = (err or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
            return False, f"ffmpeg a échoué (code {proc.returncode}) {ligne[0][:160]}".strip()
        if not mp4_complet(sortie):
            return False, "Le MP4 produit est incomplet"
        if os.path.getsize(sortie) < st.st_size * _RATIO_TAILLE_MIN:
            return False, "Le MP4 produit est trop petit : un flux a été perdu"
        livrer(sortie, cible)
        # Garder la date d'origine : 190 episodes convertis ne sont pas 190 nouveautes.
        try:
            os.utime(cible, (st.st_atime, st.st_mtime))
        except OSError:
            pass
        if os.path.normcase(os.path.abspath(cible)) != os.path.normcase(os.path.abspath(source)):
            supprimer_silencieux(source)
        return True, "Converti en MP4"
    finally:
        if travail:
            shutil.rmtree(travail, ignore_errors=True)


def reparer_un(chemin: str) -> tuple[bool, str]:
    """Rejuge le fichier maintenant : rien ne s'applique sur un diagnostic perime."""
    from engine.library.scanner import est_dans_downloads

    if not est_dans_downloads(chemin):
        return False, "Hors des dossiers de la librairie"
    p = classer(chemin)
    if p is None:
        return True, "Déjà sain"
    if p["action"] == SUPPRIMER:
        os.remove(chemin)
        return True, "Supprimé"
    if p["action"] == RENOMMER:
        if os.path.exists(p["cible"]):
            return False, "Le nom final est déjà pris"
        os.replace(chemin, p["cible"])
        return True, "Renommé"
    return _convertir(chemin, p["cible"])


def _executer(chemins: list[str]) -> None:
    try:
        for chemin in chemins:
            if _annulation.is_set():
                break
            with _verrou:
                _etat["courant"] = os.path.basename(chemin)
            try:
                ok, message = reparer_un(chemin)
            except Exception as e:
                log.warning("santé : réparation de %s impossible", os.path.basename(chemin), exc_info=True)
                ok, message = False, str(e)[:200]
            with _verrou:
                _etat["faits"] += 1
                if ok:
                    _etat["reussis"] += 1
                elif not _annulation.is_set():
                    _etat["echecs"].append({"chemin": chemin, "message": message})
    finally:
        from engine.library.scanner import invalider_cache_librairie
        from engine.library.updates import invalider_cache_updates
        invalider_cache_librairie()
        invalider_cache_updates()
        with _verrou:
            _etat.update(en_cours=False, courant="", annule=_annulation.is_set(),
                         termine_a=int(time.time()))
            bilan = (_etat["reussis"], _etat["total"])
        log.info("santé : réparation terminée — %d/%d réussie(s)", *bilan)


def demarrer_reparation(chemins: list[str]) -> dict:
    chemins = list(dict.fromkeys(c for c in chemins if isinstance(c, str) and c))
    if not chemins:
        return {"ok": False, "message": "Rien à réparer"}
    with _verrou:
        if _etat["en_cours"]:
            return {"ok": False, "message": "Une réparation est déjà en cours"}
        _annulation.clear()
        _etat.update(en_cours=True, total=len(chemins), faits=0, reussis=0,
                     courant="", echecs=[], annule=False, termine_a=0)
    threading.Thread(target=_executer, args=(chemins,), daemon=True, name="sante-librairie").start()
    return {"ok": True, "total": len(chemins)}


def annuler_reparation() -> None:
    # Hors reparation, lever le drapeau le laisserait perime : l'arret de l'app
    # l'appelle a chaque fois, et la conversion suivante se dirait « Annulee ».
    with _verrou:
        if _etat["en_cours"]:
            _annulation.set()
        proc = _proc
    if proc is not None and proc.poll() is None:
        terminate_tree(proc)
