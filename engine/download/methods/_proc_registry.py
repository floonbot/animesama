
import logging
import subprocess
import threading
from typing import Any

log = logging.getLogger("engine.download.proc_registry")

_actifs: set[subprocess.Popen[Any]] = set()
_lock = threading.Lock()
_cancel_en_cours = False
_pause_en_cours = False

try:
    import psutil as _psutil
except ImportError:  # pragma: no cover
    _psutil = None
    log.warning("psutil indisponible — pause/reprise des téléchargements désactivée")

def _est_fini(proc: subprocess.Popen[Any]) -> bool:
    try:
        return proc.poll() is not None
    except Exception:
        return True

def _purger_process_termines_verrou_tenu() -> None:
    for fini in [p for p in _actifs if _est_fini(p)]:
        _actifs.discard(fini)

def set_pause_state(actif: bool) -> None:
    global _pause_en_cours
    with _lock:
        _pause_en_cours = bool(actif)

def register_proc(proc: subprocess.Popen[Any] | None) -> None:
    if proc is None:
        return
    with _lock:
        _purger_process_termines_verrou_tenu()
        if _cancel_en_cours:
            a_tuer = proc
        else:
            _actifs.add(proc)
            a_tuer = None
            if _pause_en_cours:
                for p in _psutil_tree(proc):
                    try:
                        p.suspend()
                    except Exception:
                        log.debug("register_proc pause : suspend échoué", exc_info=True)
    if a_tuer is not None:
        try:
            from engine.download._engine_utils import terminate_tree
            terminate_tree(a_tuer)
        except Exception as e:
            log.debug(f"register_proc annulation en cours : {e}")

def unregister_proc(proc: subprocess.Popen[Any] | None) -> None:
    if proc is None:
        return
    with _lock:
        _actifs.discard(proc)

def kill_all_processes() -> int:
    from engine.download._engine_utils import terminate_tree

    global _cancel_en_cours
    with _lock:
        _cancel_en_cours = True
        procs = list(_actifs)
        _actifs.clear()

    tues = 0
    for proc in procs:
        try:
            if proc.poll() is not None:
                continue
            terminate_tree(proc)
            tues += 1
        except Exception as e:
            log.debug(f"kill_all_processes : {e}")
    with _lock:
        _cancel_en_cours = False
    return tues

def _psutil_tree(proc: subprocess.Popen[Any]) -> list[Any]:
    if _psutil is None:
        return []
    try:
        p = _psutil.Process(proc.pid)
        return [p, *p.children(recursive=True)]
    except Exception:
        return []

def _apply_tree(action: str) -> int:
    with _lock:
        procs = list(_actifs)
    n = 0
    for proc in procs:
        try:
            if proc.poll() is not None:
                continue
        except Exception:
            continue
        for p in _psutil_tree(proc):
            try:
                getattr(p, action)()
                n += 1
            except Exception:
                log.debug("%s failed on pid %s", action, getattr(p, "pid", "?"), exc_info=True)
    return n

def suspend_all() -> int:
    return _apply_tree("suspend")

def resume_all() -> int:
    return _apply_tree("resume")

def is_suspended(proc: subprocess.Popen[Any] | None) -> bool:
    if proc is None or _psutil is None:
        return False
    try:
        return _psutil.Process(proc.pid).status() == _psutil.STATUS_STOPPED
    except Exception:
        return False
