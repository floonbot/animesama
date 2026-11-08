
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable

log = logging.getLogger("engine.download.methods.ffmpeg_engine")

from engine.config.settings import DEFAULT_USER_AGENT, TAILLE_MIN_FFMPEG
from engine.domain.exceptions import DownloadCancelled
from engine.download._engine_utils import (
    NO_WINDOW_FLAGS,
    borner_nom_fichier,
    clean_subprocess_env,
    creer_dossier_de_travail,
    finaliser_process,
    livrer,
)
from engine.download._engine_utils import (
    est_url_http as _est_url_http,
)
from engine.download._engine_utils import (
    safe_callback as _safe_callback,
)
from engine.download._engine_utils import (
    safe_header as _safe_header,
)
from engine.download._engine_utils import (
    spawn_proc_watchdog as _spawn_proc_watchdog,
)
from engine.download._engine_utils import (
    terminate_tree as _terminate_tree,
)
from engine.download.methods._ffmpeg_parsing import (
    ProgressState as _ProgressState,
)
from engine.download.methods._ffmpeg_parsing import (
    construire_commande as _construire_commande,
)
from engine.download.methods._ffmpeg_parsing import (
    construire_texte_progress as _construire_texte_progress,
)
from engine.download.methods._ffmpeg_parsing import (
    parse_progress_line as _parse_progress_line,
)
from engine.download.methods._proc_registry import register_proc, unregister_proc
from engine.observability.redact import redact_text, redact_url

TAILLE_MIN_FICHIER = TAILLE_MIN_FFMPEG
TIMEOUT_FFMPEG     = 3600
STALL_FFMPEG       = 600

def _find_ffmpeg() -> str | None:
    try:
        from engine.config.settings import _BUNDLE_DIR, ROOT_DIR
        bases = [os.path.join(str(ROOT_DIR), "bin"), str(ROOT_DIR)]
        if getattr(sys, "frozen", False):
            bases.append(os.path.join(str(_BUNDLE_DIR), "bin"))
        for base in bases:
            for nom in ("ffmpeg.exe", "ffmpeg"):
                chemin = os.path.join(base, nom)
                if os.path.exists(chemin):
                    return chemin
    except (ImportError, OSError):
        pass
    return shutil.which("ffmpeg")

_FFMPEG_PATH = _find_ffmpeg()
if _FFMPEG_PATH:
    log.debug(f"ffmpeg détecté : {_FFMPEG_PATH}")
else:
    log.debug("ffmpeg introuvable — last resort désactivé")

def _get_ffmpeg_path() -> str | None:
    global _FFMPEG_PATH
    if _FFMPEG_PATH and os.path.exists(_FFMPEG_PATH):
        return _FFMPEG_PATH
    _FFMPEG_PATH = _find_ffmpeg()
    return _FFMPEG_PATH

def _valider_sortie_ffmpeg(
    proc, sortie: str, nom: str, callback: Callable[[float, str], None] | None
) -> str | None:
    if proc.returncode == 0 and os.path.exists(sortie):
        taille = os.path.getsize(sortie)
        if taille >= TAILLE_MIN_FICHIER:
            taille_mb = taille // 1024 // 1024
            log.info(f"[ffmpeg] ✅ Succès — {nom} ({taille_mb} MB)")
            _safe_callback(callback, 100.0, "✅ Téléchargement terminé !")
            return sortie
        else:
            log.warning(f"[ffmpeg] Fichier trop petit ({taille} o) — considéré comme échec")
            try:
                os.remove(sortie)
            except OSError:
                pass
    else:
        log.warning(f"[ffmpeg] Code retour : {proc.returncode}")
    return None

def _lire_stdout_ffmpeg(
    pipe, state: _ProgressState, stdout_ready: threading.Event
) -> None:
    try:
        for line in pipe:
            line = line.rstrip()
            if line:
                _parse_progress_line(line, state)
    except Exception:
        log.debug("ffmpeg stdout reader error", exc_info=True)
    finally:
        stdout_ready.set()

def _purger_si_trop_petit(sortie: str, seuil: int) -> None:
    if os.path.exists(sortie):
        try:
            if os.path.getsize(sortie) < seuil:
                os.remove(sortie)
        except OSError:
            pass

def _taille_ou_none(chemin: str) -> int | None:
    try:
        return os.path.getsize(chemin)
    except OSError:
        return None

def _supprimer_sortie_incomplete(sortie: str, avant: int | None) -> bool:
    """Retire la video que cette tentative a ecrite sans aboutir.

    Meme defaut que celui corrige sur yt-dlp au C14, par un autre chemin :
    ffmpeg ecrit directement dans le fichier final. Coupe en route, il laissait
    tout ce qui depassait TAILLE_MIN_FFMPEG (2 Mo) — un partiel que
    `nm3u8dl._trouver_fichier_final` adoptait ensuite comme un succes, et que
    `skip_existants` prenait pour un episode deja telecharge.

    On ne touche qu'a ce que cette tentative a ecrit : un fichier deja complet,
    inchange depuis le depart, n'a pas a disparaitre sur un echec.
    """
    apres = _taille_ou_none(sortie)
    if apres is None or apres == avant:
        return False
    try:
        os.remove(sortie)
    except OSError:
        return False
    log.info(
        "[ffmpeg] sortie incomplète supprimée (%d o) — le moteur suivant "
        "repart de zéro au lieu de l'adopter", apres,
    )
    return True

def ffmpeg_download(
    url:       str,
    dossier:   str,
    nom:       str,
    headers:   dict[str, str] | None = None,
    cancelled: list[bool] | None = None,
    callback:  Callable[[float, str], None] | None = None,
) -> str | None:
    exe = _get_ffmpeg_path()
    if not exe:
        msg = "ffmpeg introuvable — installe ffmpeg et assure-toi qu'il est dans le PATH."
        log.warning(msg)
        _safe_callback(callback, 0.0, f"⚠️ {msg}")
        return None

    if not _est_url_http(url):
        log.warning(f"URL invalide pour ffmpeg : {redact_url(url, 80)}")
        return None

    try:
        os.makedirs(dossier, exist_ok=True)
    except OSError as e:
        log.error(f"[ffmpeg] Dossier impossible à créer '{dossier}' : {e}")
        _safe_callback(callback, 0.0, "⚠️ Impossible de créer le dossier de téléchargement (emplacement ou droits)")
        return None
    nom = borner_nom_fichier(dossier, nom, ".mp4")
    sortie = os.path.join(dossier, nom + ".mp4")

    log.info(f"[ffmpeg] Téléchargement last resort : {nom}")
    log.debug(f"[ffmpeg] URL : {redact_url(url)}")
    log.debug("[ffmpeg] Options : reconnect=1, threads=0, stream-copy")

    proc = None
    watchdog = None
    state = _ProgressState()
    taille_avant = _taille_ou_none(sortie)
    chemin_valide: str | None = None
    travail: str | None = None

    stdout_ready = threading.Event()

    try:
        # +faststart reecrit le fichier en fin de mux, ce qu'un partage SMB refuse :
        # on ecrit en local et on ne livre que le fichier valide (voir livrer).
        # Cree dans le try : le finally le retire quoi qu'il arrive ensuite.
        try:
            travail = creer_dossier_de_travail()
        except OSError as e:
            log.debug(f"[ffmpeg] dossier de travail local indisponible ({e}) — écriture directe")
        ecriture = os.path.join(travail, "video.mp4") if travail else sortie
        cmd = _construire_commande(exe, url, ecriture, headers or {})
        duree_totale_s = _estimer_duree_hls(url, headers or {})

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=clean_subprocess_env(),
            creationflags=NO_WINDOW_FLAGS,
            start_new_session=True,
        )
        register_proc(proc)
        activity = [time.time()]
        watchdog = _spawn_proc_watchdog(proc, cancelled, TIMEOUT_FFMPEG, activity, STALL_FFMPEG)

        t_stdout = threading.Thread(
            target=_lire_stdout_ffmpeg,
            args=(proc.stdout, state, stdout_ready),
            daemon=True,
            name="ffmpeg-progress",
        )
        t_stdout.start()

        _safe_callback(callback, 0.0, "🔴 Téléchargement (méthode alternative)…")

        last_emit = time.time()
        if proc.stderr:
            for ligne in proc.stderr:
                activity[0] = time.time()
                ligne = ligne.rstrip()
                if not ligne:
                    continue

                if cancelled and cancelled[0]:
                    _terminate_tree(proc)
                    raise DownloadCancelled()

                now = time.time()
                if now - last_emit >= 0.5:
                    pct, texte = _construire_texte_progress(state, duree_totale_s)
                    if texte and texte != "⏱ 00:00:00 · ?":
                        _safe_callback(callback, pct, f"⬇️ {texte}")
                    last_emit = now

                if any(kw in ligne for kw in ("Error", "error", "Invalid", "fatal", "Failed")):
                    log.warning(f"[ffmpeg] {redact_text(ligne)[:200]}")

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            log.warning("[ffmpeg] process non terminé après EOF — kill")
            _terminate_tree(proc)
        t_stdout.join(timeout=2)

        if cancelled and cancelled[0]:
            raise DownloadCancelled()

        valide = _valider_sortie_ffmpeg(proc, ecriture, nom, callback)
        if valide and travail:
            livrer(valide, sortie)
            valide = sortie
        chemin_valide = valide
        return chemin_valide

    except RuntimeError:
        raise
    except FileNotFoundError as e:
        log.error(f"[ffmpeg] Exécutable manquant : {e}")
        return None
    except Exception as e:
        log.error(f"[ffmpeg] Erreur inattendue : {e}")
        return None
    finally:
        finaliser_process(proc, watchdog, _terminate_tree)
        if proc is not None:
            for _flux in (proc.stdout, proc.stderr):
                if _flux is not None:
                    try:
                        _flux.close()
                    except Exception:
                        pass
        if chemin_valide is None:
            _supprimer_sortie_incomplete(sortie, taille_avant)
        _purger_si_trop_petit(sortie, TAILLE_MIN_FICHIER)
        if travail:
            shutil.rmtree(travail, ignore_errors=True)
        unregister_proc(proc)

def _estimer_duree_hls(url: str, headers: dict[str, str]) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0

    ua      = _safe_header(headers.get("user-agent") or DEFAULT_USER_AGENT)
    referer = _safe_header(headers.get("referer") or "")

    cmd = [
        ffprobe,
        "-v",           "quiet",
        "-print_format", "json",
        "-show_format",
        "-protocol_whitelist", "crypto,http,https,tcp,tls",
        "-user_agent",  ua,
    ]
    if referer:
        cmd += ["-referer", referer]
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3,
            env=clean_subprocess_env(),
            creationflags=NO_WINDOW_FLAGS,
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            dur  = float(data.get("format", {}).get("duration", 0))
            if dur > 0:
                log.debug(f"[ffmpeg] Durée estimée : {dur:.0f}s")
            return dur
    except Exception:
        pass
    return 0.0
