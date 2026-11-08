import logging
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("engine.download.engine_utils")

NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

MAX_PATH_NT = 250
_RE_SUFFIXE_EPISODE = re.compile(r"\s-\s(?:S\d{2,}E\d{2,}|.*?\s-\s+E\d{2,})\b.*$")

def borner_nom_fichier(dossier: str, nom: str, ext: str = "", silencieux: bool = False) -> str:
    if os.name != "nt":
        return nom
    complet = os.path.join(dossier, nom + ext)
    if len(complet) <= MAX_PATH_NT:
        return nom
    trop = len(complet) - MAX_PATH_NT
    m = _RE_SUFFIXE_EPISODE.search(nom)
    # Le numero d'episode distingue les fichiers : on rogne le titre, jamais le suffixe.
    suffixe = m.group(0) if m else ""
    tete = nom[: m.start()] if m else nom
    tete = tete[: max(1, len(tete) - trop)].rstrip(" .-")
    court = (tete + suffixe).strip()
    if not silencieux:
        log.warning(
            "Chemin trop long pour Windows (%d car.) — nom raccourci : %s", len(complet), court
        )
    return court or nom[:MAX_PATH_NT]

def mp4_complet(chemin: str) -> bool:
    """Le conteneur a ete ferme : boites entieres jusqu'a la fin, et un moov.

    ffmpeg n'ecrit le moov qu'en fin de mux et laisse d'ici la la taille de mdat
    a 0 (« jusqu'a la fin du fichier ») : un mux coupe en route n'a pas de moov.
    On ne lit que les en-tetes de boites — quelques octets chacune, meme sur un
    partage reseau.
    """
    try:
        taille = os.path.getsize(chemin)
        with open(chemin, "rb") as f:
            pos = 0
            moov = False
            while pos < taille:
                f.seek(pos)
                entete = f.read(8)
                if len(entete) < 8:
                    return False
                longueur, type_boite = struct.unpack(">I4s", entete)
                if longueur == 1:
                    etendue = f.read(8)
                    if len(etendue) < 8:
                        return False
                    longueur = struct.unpack(">Q", etendue)[0]
                elif longueur == 0:
                    longueur = taille - pos
                if longueur < 8 or pos + longueur > taille:
                    return False
                moov = moov or type_boite == b"moov"
                pos += longueur
            return moov
    except OSError:
        return False

# Les moteurs ecrivent d'abord ici, puis livrent dans le dossier de telechargement.
# Mesure du 06/11/2026 sur un partage SMB de NAS : ffmpeg -movflags +faststart
# y echoue en fin de course (« Error writing trailer: Invalid argument ») alors
# que la meme commande reussit sur un disque local. _remux_fix procedait deja
# ainsi, et c'etait le seul chemin qui marchait.
_PREFIXE_TRAVAIL = "animesama_travail_"
_TRAVAIL_PERIME_S = 86_400  # un episode est coupe a 3 h 30 : au-dela, run tue

def creer_dossier_de_travail() -> str:
    """Dossier local jetable ; l'appelant le retire. Purge ceux d'un run tue."""
    base = tempfile.gettempdir()
    limite = time.time() - _TRAVAIL_PERIME_S
    try:
        for entree in os.scandir(base):
            if entree.name.startswith(_PREFIXE_TRAVAIL) and entree.is_dir(follow_symlinks=False):
                if entree.stat().st_mtime < limite:
                    shutil.rmtree(entree.path, ignore_errors=True)
    except OSError:
        log.debug("purge des dossiers de travail impossible", exc_info=True)
    return tempfile.mkdtemp(prefix=_PREFIXE_TRAVAIL)

def livrer(source: str, destination: str) -> None:
    """Pose le fichier fini a sa place, sans jamais y exposer un fichier partiel.

    Sur un autre volume, une copie coupee en route laisserait sinon une video
    tronquee sous le nom final — que skip_existants prendrait pour l'episode.
    """
    try:
        os.replace(source, destination)
        return
    except OSError:
        pass  # autre volume : copie sous un nom provisoire, puis renommage sur place
    provisoire = destination + ".livraison"
    try:
        shutil.copyfile(source, provisoire)
        os.replace(provisoire, destination)
    except BaseException:
        supprimer_silencieux(provisoire)
        raise
    supprimer_silencieux(source)

def clean_subprocess_env() -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return env
    norm = os.path.normcase(os.path.normpath(meipass))
    for var in ("PATH", "LD_LIBRARY_PATH"):
        val = env.get(var)
        if not val:
            continue
        env[var] = os.pathsep.join(
            p for p in val.split(os.pathsep)
            if p and os.path.normcase(os.path.normpath(p)) != norm
        )
    for k in list(env):
        if k.startswith("_PYI_"):
            env.pop(k, None)
    return env

def _kill_process_group(proc: subprocess.Popen[Any]) -> bool:
    killpg = getattr(os, "killpg", None)
    getpgid = getattr(os, "getpgid", None)
    getpgrp = getattr(os, "getpgrp", None)
    if killpg is None or getpgid is None or getpgrp is None:
        return False
    try:
        pgid = getpgid(proc.pid)
        if pgid == getpgrp():
            return False
        killpg(pgid, getattr(signal, "SIGKILL", signal.SIGTERM))
        return True
    except Exception:
        return False

def _kill_children_via_psutil(proc: subprocess.Popen[Any]) -> None:
    try:
        import psutil
    except ImportError:
        return
    if psutil is None:
        return
    try:
        parent = psutil.Process(proc.pid)
        enfants = parent.children(recursive=True)
    except Exception:
        return
    for child in enfants:
        try:
            child.kill()
        except Exception:
            log.debug("kill child pid %s échoué", getattr(child, "pid", "?"), exc_info=True)

def terminate_tree(proc: subprocess.Popen[Any] | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
    except Exception:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return
        except Exception as e:
            log.debug("taskkill failed (%s) — fallback terminate", e)
    elif _kill_process_group(proc):
        return
    _kill_children_via_psutil(proc)
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def finaliser_process(
    proc: subprocess.Popen[Any] | None,
    watchdog: threading.Event | None,
    terminate: Callable[[subprocess.Popen[Any] | None], None] = terminate_tree,
) -> None:
    if watchdog is not None:
        watchdog.set()
    if proc is not None and proc.poll() is None:
        try:
            terminate(proc)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
        except Exception:
            pass

def spawn_proc_watchdog(
    proc: subprocess.Popen[Any],
    cancelled: Any,
    timeout_s: float,
    activity: list[float] | None = None,
    stall_s: float = 0.0,
) -> threading.Event:
    from engine.observability.context import get_task_id, set_task_id

    stop = threading.Event()
    deadline_ts = time.time() + max(1.0, timeout_s)
    tid = get_task_id()

    def _run() -> None:
        if tid:
            set_task_id(tid)
        nonlocal deadline_ts
        from engine.download.methods._proc_registry import is_suspended
        last_tick = time.time() if activity is not None else 0.0
        while not stop.wait(0.5):
            try:
                if proc.poll() is not None:
                    return
                if is_suspended(proc):
                    deadline_ts += 0.5
                    if activity is not None:
                        activity[0] = time.time()
                    continue
                cancelled_now = bool(cancelled and cancelled[0])
                now = time.time()
                if activity is not None:
                    jump = now - last_tick
                    last_tick = now
                    if jump > 5.0:
                        deadline_ts += jump
                        activity[0] = now
                        continue
                expired = now >= deadline_ts
                stalled = (
                    stall_s > 0
                    and activity is not None
                    and (now - activity[0]) > stall_s
                )
                if cancelled_now or expired or stalled:
                    if stalled and not cancelled_now and not expired:
                        log.error("download watchdog: stall timeout reached — killing process")
                    elif expired and not cancelled_now:
                        log.error("download watchdog: global timeout reached — killing process")
                    terminate_tree(proc)
                    return
            except Exception:
                log.debug("download watchdog crashed", exc_info=True)
                return

    t = threading.Thread(target=_run, daemon=True, name="dl-watchdog")
    t.start()
    return stop

def est_url_http(url: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        return urlparse(url).scheme.lower() in ("http", "https")
    except Exception:
        return False

def token_annule(token: Any) -> bool:
    if token is None:
        return False
    try:
        return bool(token.is_cancelled())
    except AttributeError:
        try:
            return bool(token[0])
        except (IndexError, TypeError):
            return False

def safe_header(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\r", "").replace("\n", "").replace("\0", "").strip()

def safe_callback(callback: Callable[[float, str], None] | None, pct: float, ligne: str) -> None:
    if not callback:
        return
    try:
        callback(pct, ligne)
    except Exception as e:
        log.debug(f"[callback] {e}")

def supprimer_silencieux(chemin: str) -> None:
    if os.path.exists(chemin):
        try:
            os.remove(chemin)
        except OSError as e:
            log.debug(f"Suppression {chemin} : {e}")

def fmt_speed(bps: float) -> str:
    if bps <= 0:
        return "—"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} MB/s"
    if bps >= 1_000:
        return f"{bps / 1_000:.0f} KB/s"
    return f"{bps:.0f} B/s"

def fmt_eta(secs: int) -> str:
    if secs <= 0:
        return ""
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h}h{m:02d}m"
    if m > 0:
        return f"{m}m{s:02d}s"
    return f"{s}s"
