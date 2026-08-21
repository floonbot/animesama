
import copy
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable

log = logging.getLogger("engine.download.methods.nm3u8dl")

REMUX_TIMEOUT       = 300
NM3U8DL_LOG_CWD = os.path.join(tempfile.gettempdir(), "anime_sama_nm3u8dl")

from engine.config.settings import TAILLE_MIN_NM3U8DL, VIDEO_EXTENSIONS
from engine.download._engine_utils import (
    NO_WINDOW_FLAGS,
    borner_nom_fichier,
    clean_subprocess_env,
)
from engine.download._engine_utils import (
    est_url_http as _est_url_http,
)
from engine.download._engine_utils import (
    fmt_eta as _fmt_eta,
)
from engine.download._engine_utils import (
    fmt_speed as _fmt_speed,
)
from engine.download._engine_utils import (
    safe_callback as _safe_callback,
)
from engine.download._engine_utils import (
    spawn_proc_watchdog as _spawn_proc_watchdog,
)
from engine.download._engine_utils import (
    supprimer_silencieux as _supprimer_silencieux,
)
from engine.download._engine_utils import (
    terminate_tree as _terminate_tree,
)
from engine.download.methods._nm3u8dl_parsing import (
    construire_commande as _construire_commande,
)
from engine.download.methods._nm3u8dl_parsing import (
    get_thread_count as _get_thread_count,
)
from engine.download.methods._nm3u8dl_parsing import (
    interpreter_ligne as _interpreter_ligne,
)
from engine.download.methods._proc_registry import (
    is_suspended,
    register_proc,
    unregister_proc,
)
from engine.observability.redact import redact_url

TAILLE_MIN_FICHIER = TAILLE_MIN_NM3U8DL
EXTENSIONS_VIDEO   = VIDEO_EXTENSIONS

def _find_nm3u8dl() -> str | None:
    racines: list[str] = []
    try:
        from engine.config.settings import _BUNDLE_DIR, ROOT_DIR
        racines.append(os.path.join(str(ROOT_DIR), "bin"))
        racines.append(str(ROOT_DIR))
        if getattr(sys, "frozen", False):
            racines.append(os.path.join(str(_BUNDLE_DIR), "bin"))
    except ImportError:
        pass
    try:
        racines.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    except Exception:
        pass

    candidats: list[str] = []
    for r in racines:
        candidats.append(os.path.join(r, "N_m3u8DL-RE.exe"))
        candidats.append(os.path.join(r, "N_m3u8DL-RE"))
    candidats.append(shutil.which("N_m3u8DL-RE.exe") or "")
    candidats.append(shutil.which("N_m3u8DL-RE") or "")

    for c in candidats:
        if c and os.path.exists(c):
            return c
    return None

_NM3U8DL_PATH = _find_nm3u8dl()
_nm3u8dl_search_lock = threading.Lock()

_NM3U8DL_LAST_SEARCH_TS: float = 0.0
_NM3U8DL_SEARCH_COOLDOWN = 30.0

if _NM3U8DL_PATH:
    log.debug(f"N_m3u8DL-RE détecté : {_NM3U8DL_PATH}")
else:
    log.warning(
        "N_m3u8DL-RE introuvable — place 'N_m3u8DL-RE.exe' à la racine du projet. "
        f"Nouvelle recherche toutes les {_NM3U8DL_SEARCH_COOLDOWN:.0f}s."
    )

def _get_nm3u8dl_path() -> str | None:
    global _NM3U8DL_PATH, _NM3U8DL_LAST_SEARCH_TS
    if _NM3U8DL_PATH and os.path.exists(_NM3U8DL_PATH):
        return _NM3U8DL_PATH
    with _nm3u8dl_search_lock:
        if _NM3U8DL_PATH and os.path.exists(_NM3U8DL_PATH):
            return _NM3U8DL_PATH
        now = time.time()
        if now - _NM3U8DL_LAST_SEARCH_TS < _NM3U8DL_SEARCH_COOLDOWN:
            return None
        _NM3U8DL_LAST_SEARCH_TS = now
        _NM3U8DL_PATH = _find_nm3u8dl()
        if _NM3U8DL_PATH:
            log.debug(f"N_m3u8DL-RE trouvé tardivement : {_NM3U8DL_PATH}")
    return _NM3U8DL_PATH

_settings_cache: dict | None = None
_settings_cache_ts: float = 0.0
_SETTINGS_CACHE_TTL = 30.0
_settings_cache_lock = threading.Lock()

def invalider_cache_settings() -> None:
    global _settings_cache, _settings_cache_ts
    with _settings_cache_lock:
        _settings_cache = None
        _settings_cache_ts = 0.0

def _get_user_settings() -> dict:
    global _settings_cache, _settings_cache_ts
    now = time.time()
    with _settings_cache_lock:
        if _settings_cache is not None and (now - _settings_cache_ts) < _SETTINGS_CACHE_TTL:
            return copy.deepcopy(_settings_cache)
    try:
        from engine.config.user_settings import load_settings
        s = load_settings()
        if not isinstance(s, dict):
            raise TypeError("settings invalide")
        with _settings_cache_lock:
            _settings_cache = s
            _settings_cache_ts = now
        return copy.deepcopy(s)
    except Exception as e:
        log.debug(f"_get_user_settings (fallback défaut) : {e}")
        return {"qualite": "auto", "thread_count": 16, "downloads_dir": ""}

def _empreinte_fichier(chemin: str) -> tuple[int, int] | None:
    """(taille, mtime_ns) — la taille seule ne suffit pas.

    Re-telecharger la meme source produit tres plausiblement un fichier de
    taille identique : s'en tenir a la taille ferait passer un vrai succes pour
    un reliquat. Le mux ecrit le fichier, donc son mtime change forcement.
    """
    try:
        st = os.stat(chemin)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)

def _sorties_video(dossier: str, nom: str) -> dict[str, tuple[int, int]]:
    """Etat des sorties possibles avant de lancer le binaire."""
    etat: dict[str, tuple[int, int]] = {}
    for ext in EXTENSIONS_VIDEO:
        chemin = os.path.join(dossier, nom + ext)
        emp = _empreinte_fichier(chemin)
        if emp is not None:
            etat[chemin] = emp
    return etat

def _trouver_fichier_final(
    dossier: str, nom: str, avant: dict[str, tuple[int, int]] | None = None
) -> str | None:
    """Le fichier produit par *cette* execution, pas n'importe quel homonyme.

    Le seul critere etait « porte le bon nom et depasse 10 Mo » : un partiel
    laisse par ffmpeg passait donc pour un succes nm3u8dl, et l'episode etait
    inscrit comme telecharge. `avant` est l'instantane pris avant Popen ; une
    entree strictement inchangee depuis n'a pas ete ecrite ici.
    """
    for ext in EXTENSIONS_VIDEO:
        chemin = os.path.join(dossier, nom + ext)
        emp = _empreinte_fichier(chemin)
        if emp is None or emp[0] <= TAILLE_MIN_FICHIER:
            continue
        if avant is not None and avant.get(chemin) == emp:
            log.warning(
                "Fichier « %s » inchangé depuis le début de cette tentative — "
                "il vient d'un autre moteur, pas de N_m3u8DL-RE : ignoré",
                os.path.basename(chemin),
            )
            continue
        return chemin
    return None

def _nettoyer_residus_mux(dossier: str, nom: str) -> int:
    removed = 0
    for ext in EXTENSIONS_VIDEO:
        residu = os.path.join(dossier, nom + ".MUX" + ext)
        try:
            if os.path.isfile(residu):
                os.remove(residu)
                removed += 1
        except OSError:
            pass
    if removed:
        log.debug(f"{removed} résidu(s) .MUX nettoyé(s)")
    return removed

def purge_stale_tmp_dirs(max_age_s: float = 7 * 24 * 3600) -> int:
    try:
        from engine.config.settings import get_downloads_dir
        root = str(get_downloads_dir())
    except Exception:
        return 0
    now = time.time()
    removed = 0
    try:
        for dirpath, dirnames, _ in os.walk(root):
            for d in list(dirnames):
                if not d.startswith("_tmp_"):
                    continue
                full = os.path.join(dirpath, d)
                dirnames.remove(d)
                try:
                    if now - os.path.getmtime(full) > max_age_s:
                        shutil.rmtree(full, ignore_errors=True)
                        removed += 1
                except OSError:
                    continue
    except OSError:
        pass
    if removed:
        log.info("Nettoyage : %d dossier(s) de reprise périmé(s) supprimé(s)", removed)
    return removed

TIMEOUT_GLOBAL_DOWNLOAD = 3 * 3600
STALL_TIMEOUT = 600
import queue as _queue_mod

from engine.domain.exceptions import DownloadCancelled


def _lire_stdout_avec_timeout(
    proc,
    cancelled: list[bool] | None,
    callback: Callable[[float, str], None] | None,
    state: dict,
    timeout_s: int = TIMEOUT_GLOBAL_DOWNLOAD,
) -> None:
    output_q: _queue_mod.Queue = _queue_mod.Queue()

    def _reader():
        try:
            if proc.stdout:
                for ligne in proc.stdout:
                    output_q.put(ligne)
        except Exception:
            log.debug("nm3u8dl stdout reader error", exc_info=True)
        finally:
            output_q.put(None)

    reader = threading.Thread(target=_reader, daemon=True, name="nm3u8dl-reader")
    reader.start()

    deadline = time.time() + timeout_s
    last_activity = time.time()

    while True:
        if is_suspended(proc):
            deadline += 1.0
            last_activity = time.time()
            if cancelled and cancelled[0]:
                _terminate_tree(proc)
                raise DownloadCancelled() from None
            time.sleep(1.0)
            continue

        remaining = deadline - time.time()
        if remaining <= 0:
            log.error(f"Timeout global ({timeout_s // 3600}h) atteint — nm3u8dl tué")
            _terminate_tree(proc)
            raise RuntimeError("Timeout global du téléchargement")

        try:
            ligne = output_q.get(timeout=min(1.0, remaining))
        except _queue_mod.Empty:
            if cancelled and cancelled[0]:
                log.warning("Annulation demandée par l'utilisateur")
                _terminate_tree(proc)
                raise DownloadCancelled() from None
            if proc.poll() is not None:
                break
            if time.time() - last_activity > STALL_TIMEOUT:
                log.error(f"nm3u8dl inactif depuis {STALL_TIMEOUT}s — process tué")
                _terminate_tree(proc)
                raise RuntimeError("Stall: aucune activité du téléchargement") from None
            continue

        if ligne is None:
            break

        last_activity = time.time()
        ligne = (ligne or "").strip()
        if not ligne:
            continue

        log.debug(ligne)
        _interpreter_ligne(ligne, state, callback)

        if cancelled and cancelled[0]:
            log.warning("Annulation demandée par l'utilisateur")
            _terminate_tree(proc)
            raise DownloadCancelled()

def _preparer_nm3u8dl(
    url: str,
    dossier: str,
    nom: str,
    headers: dict[str, str] | None,
    callback: Callable[[float, str], None] | None,
) -> tuple[str, str, list[str], str] | None:
    exe = _get_nm3u8dl_path()
    if not exe:
        log.error("N_m3u8DL-RE.exe introuvable dans bin/ — relancer packaging/install.bat")
        if callback:
            try:
                callback(0.0, "❌ Composant de téléchargement manquant — réinstalle l'application")
            except Exception:
                pass
        return None

    if not url or not _est_url_http(url):
        log.error(f"URL invalide refusée : {redact_url(url, 60)}")
        if callback:
            try:
                callback(0.0, "❌ URL invalide")
            except Exception:
                pass
        return None
    if not nom or not isinstance(nom, str):
        log.error("Nom de fichier vide ou invalide")
        return None
    if not dossier:
        log.error("Dossier de destination vide")
        return None

    settings = _get_user_settings()
    try:
        os.makedirs(dossier, exist_ok=True)
    except OSError as e:
        log.error(f"Impossible de créer le dossier '{dossier}' : {e}")
        if callback:
            try:
                callback(0.0, "❌ Impossible de créer le dossier de téléchargement (emplacement ou droits)")
            except Exception:
                pass
        return None

    nom = borner_nom_fichier(dossier, nom, ".mp4")
    headers = headers or {}
    tmp_dir = os.path.join(dossier, "_tmp_" + nom)

    cmd = _construire_commande(
        exe, url, dossier, nom, tmp_dir, headers, settings, _find_ffmpeg(),
    )

    log.info(
        f"Téléchargement : {nom}  "
        f"(qualité {settings.get('qualite', 'auto')}, "
        f"{_get_thread_count(settings)} threads)"
    )
    log.debug(f"URL : {redact_url(url)}")
    log.debug(f"Referer : {redact_url(headers.get('referer') or headers.get('origin') or '', 80) or '(aucun)'}")
    # Le nom borne remonte au caller : c'est sous celui-la que le binaire ecrit,
    # donc sous celui-la qu'il faut chercher le fichier produit et ses residus.
    return dossier, tmp_dir, cmd, nom

def _cleanup_run(
    proc: subprocess.Popen[str] | None,
    watchdog: threading.Event | None,
    stop_monitor: threading.Event,
    monitor_thread: threading.Thread | None,
    tmp_dir: str,
    succeeded: bool,
    user_cancelled: bool,
) -> None:
    if watchdog is not None:
        watchdog.set()
    stop_monitor.set()
    if monitor_thread is not None:
        try:
            monitor_thread.join(timeout=2)
            if monitor_thread.is_alive():
                log.debug("monitor_thread n'a pas terminé sous 2s")
        except Exception:
            pass
    if proc is not None:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        if proc.poll() is None:
            try:
                _terminate_tree(proc)
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    keep_tmp = (not succeeded) and (not user_cancelled)
    if os.path.exists(tmp_dir):
        if keep_tmp:
            log.info("Segments conservés pour reprise ultérieure : %s", tmp_dir)
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    unregister_proc(proc)

def nm3u8dl_download(
    url:       str,
    dossier:   str,
    nom:       str,
    headers:   dict[str, str] | None        = None,
    cancelled: list[bool] | None  = None,
    callback:  Callable[[float, str], None] | None = None,
) -> str | None:
    prep = _preparer_nm3u8dl(url, dossier, nom, headers, callback)
    if prep is None:
        return None
    dossier, tmp_dir, cmd, nom = prep

    proc = None
    watchdog: threading.Event | None = None
    stop_monitor = threading.Event()
    monitor_thread: threading.Thread | None = None
    succeeded = False
    user_cancelled = False
    sorties_avant = _sorties_video(dossier, nom)

    try:
        try:
            os.makedirs(NM3U8DL_LOG_CWD, exist_ok=True)
        except OSError:
            pass
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=NM3U8DL_LOG_CWD if os.path.isdir(NM3U8DL_LOG_CWD) else None,
            env=clean_subprocess_env(),
            creationflags=NO_WINDOW_FLAGS,
            start_new_session=True,
        )
        register_proc(proc)
        watchdog = _spawn_proc_watchdog(proc, cancelled, TIMEOUT_GLOBAL_DOWNLOAD)

        state = {
            "total_segs": 0,
            "start_time": time.time(),
            "last_size":  0,
            "last_time":  time.time(),
            "speed_bps":  0.0,
            "phase":      "init",
        }

        monitor_thread = threading.Thread(
            target=_monitor_tmp,
            args=(tmp_dir, state, stop_monitor, callback),
            daemon=True,
        )
        monitor_thread.start()

        if proc.stdout is not None:
            _lire_stdout_avec_timeout(proc, cancelled, callback, state)

        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            log.error("N_m3u8DL-RE bloqué après la fin de stdout — kill forcé")
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        chemin = _trouver_fichier_final(dossier, nom, sorties_avant)
        if chemin:
            try:
                taille_mb = os.path.getsize(chemin) // 1024 // 1024
            except OSError:
                taille_mb = 0
            log.success(f"Téléchargement réussi — {nom} ({taille_mb} MB)")  # type: ignore[attr-defined]
            succeeded = True
            _nettoyer_residus_mux(dossier, nom)
            return _remux_fix(chemin, callback)

        log.warning(
            f"N_m3u8DL-RE n'a pas produit de fichier valide (code {proc.returncode})"
        )
        return None

    except DownloadCancelled:
        user_cancelled = True
        raise
    except RuntimeError:
        raise
    except FileNotFoundError as e:
        log.error(f"Exécutable nm3u8dl introuvable : {e}")
        return None
    except Exception as e:
        log.error(f"Erreur pendant le téléchargement : {e}")
        return None
    finally:
        _cleanup_run(
            proc, watchdog, stop_monitor, monitor_thread,
            tmp_dir, succeeded, user_cancelled,
        )

_SEGMENTS_EXT = (".ts", ".m4s", ".mp4")

def _mesurer_progression_tmp(
    tmp_dir: str,
    state: dict,
    callback: Callable[[float, str], None] | None,
) -> None:
    # Un seul scandir : sous Windows, DirEntry.stat() rend la taille lue par le
    # parcours du dossier, sans syscall supplementaire. L'ancienne boucle
    # isfile+getsize par segment coutait 90 ms par tick a 1500 segments, une
    # fois par seconde et en croissance pendant tout le telechargement.
    done = 0
    cur_size = 0
    try:
        with os.scandir(tmp_dir) as entrees:
            for e in entrees:
                if not e.name.endswith(_SEGMENTS_EXT):
                    continue
                try:
                    if not e.is_file():
                        continue
                    cur_size += e.stat().st_size
                except OSError:
                    continue
                done += 1
    except OSError:
        return

    total = state["total_segs"]

    now = time.time()
    dt  = now - state["last_time"]
    if dt >= 1.0:
        ds = cur_size - state["last_size"]
        state["speed_bps"] = max(0.0, ds / dt)
        state["last_size"] = cur_size
        state["last_time"] = now

    if total > 0 and callback and state["phase"] == "downloading":
        pct       = min(95.0, done / total * 100)
        speed_str = _fmt_speed(state["speed_bps"])
        eta_s     = int((total - done) * (now - state["start_time"]) / max(done, 1))
        eta_str   = _fmt_eta(eta_s) if eta_s > 0 and done > 0 else ""
        ligne     = f"{pct:.1f}% · {done}/{total} segments · {speed_str}"
        if eta_str:
            ligne += f" · ETA {eta_str}"
        _safe_callback(callback, pct, ligne)

def _monitor_tmp(
    tmp_dir: str,
    state:   dict,
    stop:    threading.Event,
    callback: Callable[[float, str], None] | None,
) -> None:
    while not stop.is_set():
        try:
            if not os.path.isdir(tmp_dir):
                if stop.wait(0.5):
                    return
                continue

            _mesurer_progression_tmp(tmp_dir, state, callback)

        except Exception as e:
            log.debug(f"[monitor_tmp] {e}")

        if stop.wait(1.0):
            return

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

def _remux_fix(chemin: str, callback: Callable[[float, str], None] | None = None) -> str:
    import tempfile

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        log.debug("ffmpeg introuvable — étape de remux ignorée")
        return chemin

    _safe_callback(callback, 99.0, "🔧 Correction des micro-freezes (remux)...")
    log.debug(f"Remux pour corriger les timestamps : {os.path.basename(chemin)}")

    t0 = time.time()
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="remux_")
        base        = os.path.basename(chemin)
        out_local   = os.path.join(tmpdir, "out_" + base)

        cmd = [
            ffmpeg, "-y",
            "-fflags", "+genpts+igndts",
            "-i", chemin,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            out_local,
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_subprocess_env(),
            creationflags=NO_WINDOW_FLAGS,
            start_new_session=True,
        )
        register_proc(proc)
        try:
            returncode = proc.wait(timeout=REMUX_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            log.debug(f"Remux interrompu après {REMUX_TIMEOUT}s — fichier original conservé")
            return chemin
        finally:
            unregister_proc(proc)

        if (
            returncode == 0
            and os.path.exists(out_local)
            and os.path.getsize(out_local) > 0
        ):
            try:
                dest_dir  = os.path.dirname(chemin)
                dest_temp = os.path.join(dest_dir, f".remux_tmp_{base}")
                shutil.copy2(out_local, dest_temp)
                os.replace(dest_temp, chemin)
                log.debug(f"Remux appliqué en {time.time()-t0:.1f}s")
            except OSError as e:
                log.debug(f"Remux : copie vers destination impossible ({e}) — fichier original conservé")
                _supprimer_silencieux(os.path.join(os.path.dirname(chemin), f".remux_tmp_{base}"))
        else:
            log.debug(f"Remux non appliqué (code={returncode}) — fichier original conservé")

    except Exception as e:
        log.debug(f"Remux : étape ignorée ({e}) — fichier original conservé")
    finally:
        if tmpdir:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    return chemin
