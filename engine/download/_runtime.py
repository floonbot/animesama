
import asyncio
import contextvars
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from engine.download._engine_utils import token_annule

log = logging.getLogger("engine.download.worker")

HISTORIQUE_MAX = 200

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dl_worker")

def _est_annule(queue) -> bool:
    return token_annule(getattr(queue, "_cancelled", None))

def _historique_append(queue, entree: dict[str, Any]) -> None:
    try:
        lock = getattr(queue, "_state_lock", None)
        if lock is not None:
            with lock:
                queue._history.append(entree)
                if len(queue._history) > HISTORIQUE_MAX:
                    del queue._history[:-HISTORIQUE_MAX]
        else:
            queue._history.append(entree)
            if len(queue._history) > HISTORIQUE_MAX:
                del queue._history[:-HISTORIQUE_MAX]
    except (AttributeError, TypeError):
        log.debug("history append failed", exc_info=True)
    try:
        store = getattr(queue, "_store", None)
        if store is not None:
            store.append_history(entree)
    except Exception:
        log.debug("history persist failed", exc_info=True)
    try:
        from engine.observability.metrics import metrics
        if isinstance(entree, dict):
            metrics.incr("episodes_succes", entree.get("succes", 0))
            metrics.incr("episodes_echoues", entree.get("echoues", 0))
            metrics.incr("episodes_skipped", entree.get("skipped", 0))
    except Exception:
        log.debug("metrics update failed (history)", exc_info=True)

def _historique_ajouter(queue, titre: str, langue: str, succes=0, echoues=0, skipped=0) -> None:
    _historique_append(queue, {
        "titre": titre, "langue": langue, "succes": succes, "echoues": echoues, "skipped": skipped,
    })

def _safe_emit(queue, event: str, data: dict[str, Any]) -> None:
    try:
        queue.emit(event, data)
    except Exception:
        log.debug("emit %s failed", event, exc_info=True)

_ENGINE_NAMES = {
    "ytdlp_download": "ytdlp",
    "nm3u8dl_download": "nm3u8dl",
    "ffmpeg_download": "ffmpeg",
}

def _propage_task_id(fn, tid):
    from engine.observability.context import reset_task_id, set_task_id

    def _call(*args):
        token = set_task_id(tid)
        try:
            return fn(*args)
        finally:
            reset_task_id(token)

    return _call

async def _run_in_pool(fn, *args):
    from engine.observability.context import get_task_id
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    wrapped = _propage_task_id(fn, get_task_id())
    engine = _ENGINE_NAMES.get(getattr(fn, "__name__", ""))
    if engine is None:
        return await loop.run_in_executor(_executor, ctx.run, wrapped, *args)
    t0 = time.time()
    ok = False
    try:
        result = await loop.run_in_executor(_executor, ctx.run, wrapped, *args)
        ok = bool(result)
        return result
    finally:
        try:
            from engine.observability.metrics import metrics
            elapsed = time.time() - t0
            metrics.incr(f"download_{engine}_ms", int(elapsed * 1000))
            metrics.incr(f"download_{engine}_attempts", 1)
            if ok:
                metrics.incr(f"download_{engine}_ok", 1)
                try:
                    if isinstance(result, str) and os.path.exists(result):
                        taille = os.path.getsize(result)
                        metrics.incr("bytes_total", taille)
                        metrics.incr(f"download_{engine}_bytes", taille)
                except OSError:
                    pass
            else:
                metrics.incr(f"download_{engine}_fail", 1)
            metrics.observe(f"lat_{engine}_s", elapsed)
        except Exception:
            log.debug("metrics update failed (engine %s)", engine, exc_info=True)

def _tuer_sous_process_moteur() -> None:
    try:
        from engine.download.methods._proc_registry import kill_all_processes
        kill_all_processes()
    except Exception:
        log.debug("kill sous-process moteur échoué", exc_info=True)

async def _armer_token_annulation(queue) -> None:
    token = getattr(queue, "_cancelled", None)
    if token is None:
        return
    try:
        token.set()
        await asyncio.sleep(2)
        token.clear()
    except AttributeError:
        try:
            token[0] = True
            await asyncio.sleep(2)
            token[0] = False
        except (IndexError, TypeError):
            pass

async def _signaler_annulation_engine(queue) -> None:
    _tuer_sous_process_moteur()
    await _armer_token_annulation(queue)

def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
