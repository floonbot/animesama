
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable

log = logging.getLogger("engine.download.methods.ytdlp_engine")

from engine.config.settings import TAILLE_MIN_YTDLP, VIDEO_EXTENSIONS
from engine.domain.exceptions import DownloadCancelled
from engine.download._engine_utils import (
    NO_WINDOW_FLAGS,
    borner_nom_fichier,
    clean_subprocess_env,
    finaliser_process,
)
from engine.download._engine_utils import (
    est_url_http as _est_url_http,
)
from engine.download._engine_utils import (
    safe_callback as _safe_callback,
)
from engine.download._engine_utils import (
    spawn_proc_watchdog as _spawn_proc_watchdog,
)
from engine.download._engine_utils import (
    terminate_tree as _terminate_tree,
)
from engine.download.methods._proc_registry import register_proc, unregister_proc
from engine.download.methods._ytdlp_parsing import (
    construire_commande as _construire_commande,
)
from engine.download.methods._ytdlp_parsing import (
    get_domain as _get_domain,
)
from engine.download.methods._ytdlp_parsing import (
    parser_debit as _parser_debit,
)
from engine.download.methods._ytdlp_parsing import (
    parser_progression as _parser_progression,
)
from engine.observability.redact import redact_text, redact_url

TAILLE_MIN_FICHIER = TAILLE_MIN_YTDLP
EXTENSIONS_VIDEO   = VIDEO_EXTENSIONS
TIMEOUT_GLOBAL     = 2 * 3600
STALL_YTDLP        = 600

class RateLimitError(RuntimeError):
    def __init__(self, domain: str = ""):
        self.domain = domain
        super().__init__(f"HTTP 403 — rate limit sur {domain or 'inconnu'}")

def _find_exe(noms: list[str]) -> str | None:
    racines: list[str] = []
    try:
        from engine.config.settings import _BUNDLE_DIR, ROOT_DIR
        racines.append(os.path.join(str(ROOT_DIR), "bin"))
        racines.append(str(ROOT_DIR))
        if getattr(sys, "frozen", False):
            racines.append(os.path.join(str(_BUNDLE_DIR), "bin"))
    except ImportError:
        pass

    for nom in noms:
        for racine in racines:
            chemin = os.path.join(racine, nom)
            if os.path.exists(chemin):
                return chemin
        found = shutil.which(nom)
        if found:
            return found
    return None

_YTDLP_PATH = _find_exe(["yt-dlp.exe", "yt-dlp"])
_ARIA2C_PATH = _find_exe(["aria2c.exe", "aria2c"])

if _YTDLP_PATH:
    log.debug(f"yt-dlp détecté : {_YTDLP_PATH}")
else:
    log.debug("yt-dlp introuvable — fallback désactivé")

if _ARIA2C_PATH:
    log.debug(f"aria2c détecté : {_ARIA2C_PATH} (téléchargement multi-connexions activé)")
else:
    log.debug("aria2c non trouvé (optionnel — yt-dlp seul suffira)")

def _get_ytdlp_path() -> str | None:
    global _YTDLP_PATH
    if _YTDLP_PATH and os.path.exists(_YTDLP_PATH):
        return _YTDLP_PATH
    _YTDLP_PATH = _find_exe(["yt-dlp.exe", "yt-dlp"])
    return _YTDLP_PATH

def _get_aria2c_path() -> str | None:
    global _ARIA2C_PATH
    if _ARIA2C_PATH and os.path.exists(_ARIA2C_PATH):
        return _ARIA2C_PATH
    _ARIA2C_PATH = _find_exe(["aria2c.exe", "aria2c"])
    return _ARIA2C_PATH

def _trouver_fichier_final(dossier: str, nom: str) -> str | None:
    for ext in EXTENSIONS_VIDEO:
        chemin = os.path.join(dossier, nom + ext)
        try:
            if os.path.exists(chemin) and os.path.getsize(chemin) >= TAILLE_MIN_FICHIER:
                return chemin
        except OSError:
            pass
    try:
        for f in os.listdir(dossier):
            if not f.startswith(nom):
                continue
            if f[len(nom):len(nom) + 1].isalnum():
                continue
            if f[len(nom):].lower().startswith(".temp."):
                continue
            if any(f.endswith(e) for e in EXTENSIONS_VIDEO):
                chemin = os.path.join(dossier, f)
                try:
                    if os.path.getsize(chemin) >= TAILLE_MIN_FICHIER:
                        return chemin
                except OSError:
                    pass
    except OSError:
        pass
    return None

def _valider_sortie_ytdlp(
    proc, dossier: str, nom: str, callback: Callable[[float, str], None] | None
) -> str | None:
    if proc.returncode == 0:
        chemin = _trouver_fichier_final(dossier, nom)
        if chemin:
            taille_mb = os.path.getsize(chemin) // 1024 // 1024
            log.info(f"[yt-dlp] ✅ Succès — {nom} ({taille_mb} MB)")
            _safe_callback(callback, 100.0, "✅ Téléchargement terminé !")
            return chemin
        log.warning("[yt-dlp] Processus OK mais fichier introuvable")
    else:
        log.info(f"[yt-dlp] Code retour non-nul : {proc.returncode} (cascade prend le relais)")
    return None

def _nettoyer_fragments(dossier: str, nom: str) -> int:
    try:
        entries = os.listdir(dossier)
    except OSError:
        return 0
    removed = 0
    for f in entries:
        if not f.startswith(nom):
            continue
        if f[len(nom):len(nom) + 1].isalnum():
            continue
        low = f.lower()
        reste = low[len(nom):]
        est_video = any(low.endswith(ext) for ext in EXTENSIONS_VIDEO)
        est_temp = (
            "-frag" in low
            or low.endswith(".part")
            or low.endswith(".ytdl")
            or reste.startswith(".temp.")
        )
        if est_video and not est_temp:
            continue
        chemin = os.path.join(dossier, f)
        try:
            if os.path.isfile(chemin):
                os.remove(chemin)
                removed += 1
        except OSError:
            pass
    if removed:
        log.debug(f"[yt-dlp] {removed} fragment(s)/temp nettoye(s)")
    return removed

def _sorties_video(dossier: str, nom: str) -> dict[str, int]:
    try:
        entries = os.listdir(dossier)
    except OSError:
        return {}
    etat: dict[str, int] = {}
    for f in entries:
        if not f.startswith(nom) or f[len(nom):len(nom) + 1].isalnum():
            continue
        if not any(f.lower().endswith(ext) for ext in EXTENSIONS_VIDEO):
            continue
        try:
            etat[f] = os.path.getsize(os.path.join(dossier, f))
        except OSError:
            pass
    return etat

def _supprimer_sortie_incomplete(dossier: str, nom: str, avant: dict[str, int]) -> int:
    """Retire la video laissee par un telechargement qui n'a pas abouti.

    --no-part fait ecrire yt-dlp directement dans le fichier final : coupe en
    route (annulation, abandon sur debit, watchdog), il reste un .mp4 tronque.
    Le lecteur suivant ne le refait pas, il le *reprend* par une requete Range —
    mesure sur deux sources distinctes : 140 ko du lecteur abandonne suivis de
    1,86 Mo du suivant, code retour 0 et taille finale exacte. Rien ne signale
    le fichier corrompu, et _nettoyer_fragments l'epargne puisqu'il ressemble a
    une video finie.

    On ne touche qu'a ce que cette tentative a ecrit : un fichier deja complet,
    inchange depuis le depart, n'a pas a disparaitre sur un echec.
    """
    removed = 0
    for f, taille in _sorties_video(dossier, nom).items():
        if avant.get(f) == taille:
            continue
        try:
            os.remove(os.path.join(dossier, f))
            removed += 1
        except OSError:
            pass
    if removed:
        log.info(
            f"[yt-dlp] {removed} sortie(s) incomplete(s) supprimee(s) "
            "— le lecteur suivant repart de zero au lieu de reprendre"
        )
    return removed

INTERVALLE_PROGRESSION_S = 0.4

def _nouvel_etat_progression() -> dict:
    return {"derniere_emission": 0.0}

def _progression_a_emettre(pct: float, etat: dict | None) -> bool:
    # yt-dlp ecrit une ligne de progression a chaque rafraichissement : sans
    # throttle chacune devenait un evenement SSE serialise et pousse a tous les
    # clients. nm3u8dl emet a 1 s, ffmpeg a 0,5 s — on s'aligne. Le 100 % passe
    # toujours, sinon la barre reste bloquee sur la derniere valeur emise.
    if etat is None or pct >= 99.9:
        return True
    maintenant = time.monotonic()
    if maintenant - etat["derniere_emission"] < INTERVALLE_PROGRESSION_S:
        return False
    etat["derniere_emission"] = maintenant
    return True

def _dispatch_ligne_ytdlp(
    ligne: str,
    domain: str,
    callback: Callable[[float, str], None] | None,
    etat: dict | None = None,
) -> bool:
    low = ligne.lower()
    got_403 = (
        ("403" in ligne and ("Forbidden" in ligne or "403:" in ligne))
        or "http error 429" in low
        or "429:" in ligne
        or "too many requests" in low
        or "http error 503" in low
        or "503:" in ligne
    )
    if got_403:
        log.warning(f"[yt-dlp] throttling détecté sur {domain} — rate limit probable")
        _safe_callback(callback, 0.0, f"⏳ Serveur occupé ({domain}) — pause…")

    parsed = _parser_progression(ligne)
    if parsed:
        pct, texte = parsed
        if _progression_a_emettre(pct, etat):
            _safe_callback(callback, pct, f"⬇️ {texte}")
    elif "[Merger]" in ligne or "Merging" in ligne:
        _safe_callback(callback, 97.0, "🔧 Assemblage pistes…")
    elif "[aria2c]" in ligne:
        _safe_callback(callback, 0.0, "⬇️ Téléchargement accéléré en cours…")
    elif "Destination:" in ligne or "[download]" in ligne:
        log.debug(f"[yt-dlp] {redact_text(ligne)[:120]}")
    elif "ERROR" in ligne or "error" in ligne.lower():
        log.info(f"[yt-dlp] {redact_text(ligne)[:200]}")
    return got_403

def _signaler_debit(cancelled: object, ligne: str) -> None:
    # Le token d'annulation sert aussi de canal de mesure : quand c'est un
    # SurveillantDebit, il coupe lui-meme via cancelled[0] si l'hote bride.
    signaler = getattr(cancelled, "signaler_debit", None)
    if signaler is None:
        return
    mesure = _parser_debit(ligne)
    if mesure is None:
        return
    try:
        signaler(mesure[0], mesure[1])
    except Exception:
        log.debug("[yt-dlp] signalement de débit échoué", exc_info=True)

def ytdlp_download(
    url:       str,
    dossier:   str,
    nom:       str,
    headers:   dict[str, str] | None = None,
    cancelled: list[bool] | None = None,
    callback:  Callable[[float, str], None] | None = None,
) -> str | None:
    exe = _get_ytdlp_path()
    if not exe:
        msg = "yt-dlp introuvable — place 'yt-dlp.exe' à la racine du projet."
        log.warning(msg)
        _safe_callback(callback, 0.0, f"⚠️ {msg}")
        return None

    if not _est_url_http(url):
        log.warning(f"URL invalide pour yt-dlp : {redact_url(url, 80)}")
        return None

    try:
        os.makedirs(dossier, exist_ok=True)
    except OSError as e:
        log.error(f"[yt-dlp] Dossier impossible à créer '{dossier}' : {e}")
        _safe_callback(callback, 0.0, "⚠️ Impossible de créer le dossier de téléchargement (emplacement ou droits)")
        return None

    # construire_commande borne deja le nom pour la sortie ; sans le borner ici
    # aussi, _trouver_fichier_final et _nettoyer_fragments cherchent sous un nom
    # que yt-dlp n'a jamais ecrit.
    nom = borner_nom_fichier(dossier, nom, ".mp4")

    try:
        from engine.config.user_settings import load_settings
        settings = load_settings() or {}
    except Exception:
        settings = {}

    qualite = str(settings.get("qualite") or "auto")
    cmd     = _construire_commande(exe, url, dossier, nom, headers or {}, qualite, aria2c=_get_aria2c_path())

    domain = _get_domain(url)
    log.info(f"[yt-dlp] Téléchargement : {nom} ({domain}, qualité {qualite})")
    log.debug(f"[yt-dlp] URL : {redact_url(url)}")
    if _get_aria2c_path():
        log.debug("[yt-dlp] aria2c actif (multi-connexions)")

    proc = None
    got_403 = False
    watchdog = None
    sorties_avant = _sorties_video(dossier, nom)
    chemin_valide = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=clean_subprocess_env(),
            creationflags=NO_WINDOW_FLAGS,
            start_new_session=True,
        )
        register_proc(proc)
        activity = [time.time()]
        watchdog = _spawn_proc_watchdog(proc, cancelled, TIMEOUT_GLOBAL, activity, STALL_YTDLP)

        _safe_callback(callback, 0.0, "▶️ Téléchargement démarré…")
        etat_progression = _nouvel_etat_progression()

        if proc.stdout:
            for ligne in proc.stdout:
                activity[0] = time.time()
                ligne = ligne.rstrip()
                if not ligne:
                    continue

                _signaler_debit(cancelled, ligne)

                if cancelled and cancelled[0]:
                    _terminate_tree(proc)
                    raise DownloadCancelled()

                if _dispatch_ligne_ytdlp(ligne, domain, callback, etat_progression):
                    got_403 = True

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            log.warning("[yt-dlp] process non terminé après EOF — kill")
            _terminate_tree(proc)

        if cancelled and cancelled[0]:
            raise DownloadCancelled()

        chemin = _valider_sortie_ytdlp(proc, dossier, nom, callback)
        if chemin:
            chemin_valide = chemin
            return chemin

        if got_403:
            raise RateLimitError(domain)

        return None

    except (RuntimeError, RateLimitError):
        raise
    except FileNotFoundError as e:
        log.error(f"[yt-dlp] Exécutable manquant : {e}")
        return None
    except Exception as e:
        log.error(f"[yt-dlp] Erreur inattendue : {e}")
        return None
    finally:
        finaliser_process(proc, watchdog, _terminate_tree)
        _nettoyer_fragments(dossier, nom)
        if chemin_valide is None:
            _supprimer_sortie_incomplete(dossier, nom, sorties_avant)
        unregister_proc(proc)
