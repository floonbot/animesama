from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.download.store import DownloadStore

log = logging.getLogger("engine.download.queue")

HISTORY_MAX = 200

def _item_identity(item: dict[str, Any]) -> str:
    try:
        return json.dumps(item, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(item)

_CLES_PROJETEES = ("id", "nom", "lang", "langue", "_scan", "_direct", "ep")

def _projeter_item(item: dict[str, Any]) -> dict[str, Any]:
    episodes = item.get("episodes")
    chapitres = item.get("chapitres")
    projete: dict[str, Any] = {k: item[k] for k in _CLES_PROJETEES if k in item}
    projete["episodes"] = episodes[:1] if isinstance(episodes, list) else []
    projete["chapitres"] = []
    projete["nb_episodes"] = len(episodes) if isinstance(episodes, list) else 0
    projete["nb_chapitres"] = len(chapitres) if isinstance(chapitres, list) else 0
    return projete

def _set_persistence_gauge(ok: bool) -> None:
    try:
        from engine.observability.metrics import metrics
        metrics.set_gauge("persistence_enabled", 1 if ok else 0)
    except Exception:
        log.debug("metrics persistence gauge failed", exc_info=True)

class CancelToken:

    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def __bool__(self) -> bool:
        return self._event.is_set()

    def __getitem__(self, _index: int) -> bool:
        return self._event.is_set()

class DownloadQueue:
    def __init__(self) -> None:
        self._queue: deque[dict] = deque()
        self._current: dict | None = None
        self._history: list[dict] = []
        self._listeners: list[Callable[[str, dict], None]] = []
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancelled = CancelToken()
        self._paused = threading.Event()
        self._started_at: float | None = None
        self._listeners_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._store: DownloadStore | None = None
        self._preserve_on_stop = False

    def enable_persistence(self) -> None:
        with self._state_lock:
            if self._store is not None:
                return
            try:
                from engine.download.store import DownloadStore
                self._store = DownloadStore()
            except Exception:
                log.warning("download persistence unavailable", exc_info=True)
                _set_persistence_gauge(False)
                return
        _set_persistence_gauge(True)
        self.restore()

    def _persist_queue(self) -> None:
        if self._store is None:
            return
        with self._state_lock:
            items = list(self._queue)
        try:
            self._store.save_queue(items)
        except Exception:
            log.debug("persist queue failed", exc_info=True)

    def _save_current(self, item: dict) -> None:
        if self._store is None:
            return
        try:
            self._store.save_current_sync(item)
        except Exception:
            log.debug("persist current failed", exc_info=True)

    def _clear_current(self) -> None:
        if self._store is None:
            return
        try:
            self._store.clear_current_sync()
        except Exception:
            log.debug("clear current failed", exc_info=True)

    def restore(self) -> None:
        if self._store is None:
            return
        try:
            items = self._store.load_queue()
            hist = self._store.load_history()
            current = self._store.load_current()
        except Exception:
            log.debug("restore failed", exc_info=True)
            return
        with self._state_lock:
            if items:
                self._queue = deque(items)
            if hist:
                self._history = hist
            if current is not None:
                existing = {_item_identity(it) for it in self._queue}
                if _item_identity(current) not in existing:
                    self._queue.appendleft(current)
        if items or current is not None:
            log.info("restored %d pending download(s) from disk", len(self._queue))

    def resume_pending(self) -> None:
        with self._state_lock:
            pending = bool(self._queue) and self._current is None
        if pending:
            self.emit("queue_updated", self.statut())
            self._start_worker()

    def clear_history(self) -> None:
        with self._state_lock:
            self._history = []
        if self._store is not None:
            try:
                self._store.clear_history()
            except Exception:
                log.debug("clear history store failed", exc_info=True)
        self.emit("queue_updated", self.statut())

    def subscribe(self, callback: Callable[[str, dict], None]) -> None:
        with self._listeners_lock:
            self._listeners.append(callback)

    def emit(self, event: str, data: dict[str, Any]) -> None:
        with self._listeners_lock:
            listeners = list(self._listeners)
        if not isinstance(data, dict):
            data = {"value": data}
        for callback in listeners:
            try:
                callback(event, data)
            except Exception:
                log.debug("listener failed on %s", event, exc_info=True)

    def statut(self) -> dict:
        with self._state_lock:
            current = _projeter_item(self._current) if self._current else None
            pending = [_projeter_item(it) for it in self._queue]
            history = self._history[-20:]
            elapsed = round(time.time() - self._started_at) if self._started_at else 0
        return {
            "en_cours": current,
            "queue": pending,
            "historique": history,
            "elapsed": elapsed,
            "en_pause": self._paused.is_set(),
        }

    async def ajouter(self, item: dict) -> int:
        if not isinstance(item, dict):
            log.warning("queue item ignored (not a dict)")
            return len(self._queue)
        with self._state_lock:
            self._queue.append(item)
            depth = len(self._queue) + (1 if self._current else 0)
        try:
            from engine.observability.metrics import metrics
            metrics.max_gauge("queue_depth_max", depth)
        except Exception:
            log.debug("metrics update failed (queue_depth_max)", exc_info=True)
        self._persist_queue()
        self.emit("queue_updated", self.statut())
        self._start_worker()
        return len(self._queue)

    def annuler(self) -> bool:
        with self._state_lock:
            if self._current is None:
                return False
        self._cancelled.set()
        self._paused.clear()
        try:
            from engine.download.methods._proc_registry import resume_all, set_pause_state
            set_pause_state(False)
            resume_all()
            from engine.download.methods._proc_registry import kill_all_processes
            kill_all_processes()
        except Exception:
            log.debug("cancel resume failed", exc_info=True)
        self._persist_queue()
        self._clear_current()
        self.emit("queue_updated", self.statut())
        self._cancel_current_item_threadsafe()
        return True

    def shutdown_preserve(self) -> bool:
        with self._state_lock:
            if self._current is None:
                return False
        self._preserve_on_stop = True
        self._paused.clear()
        try:
            from engine.download.methods._proc_registry import (
                kill_all_processes,
                resume_all,
                set_pause_state,
            )
            set_pause_state(False)
            resume_all()
            kill_all_processes()
        except Exception:
            log.debug("shutdown_preserve kill failed", exc_info=True)
        self.emit("queue_updated", self.statut())
        self._cancel_task_threadsafe()
        return True

    def _cancel_task_threadsafe(self) -> None:
        task, loop = self._task, self._loop
        if task is None or task.done():
            return
        try:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(task.cancel)
            else:
                task.cancel()
        except RuntimeError:
            log.debug("cancel: loop unavailable", exc_info=True)

    def _cancel_current_item_threadsafe(self) -> None:
        # annuler() ne stoppe que l'item courant : le worker enchaine sur la file.
        # Le cancel est poste sur la boucle et re-teste _cancelled une fois dedans,
        # car _run le remet a zero entre deux items — sans ce garde, une annulation
        # qui arrive juste apres la fin de l'item tuerait le suivant.
        def _si_toujours_annule() -> None:
            if not self._cancelled.is_cancelled():
                return
            task = self._task
            if task is not None and not task.done():
                task.cancel()

        task, loop = self._task, self._loop
        if task is None or task.done():
            return
        try:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(_si_toujours_annule)
            else:
                _si_toujours_annule()
        except RuntimeError:
            log.debug("cancel: loop unavailable", exc_info=True)

    def pause(self) -> bool:
        with self._state_lock:
            if self._current is None:
                return False
        self._paused.set()
        try:
            from engine.download.methods._proc_registry import set_pause_state, suspend_all
            set_pause_state(True)
            n = suspend_all()
            if n:
                log.info("pause: %d process de téléchargement suspendu(s)", n)
        except Exception:
            log.debug("pause suspend failed", exc_info=True)
        self.emit("queue_updated", self.statut())
        return True

    def reprendre(self) -> bool:
        self._paused.clear()
        try:
            from engine.download.methods._proc_registry import resume_all, set_pause_state
            set_pause_state(False)
            resume_all()
        except Exception:
            log.debug("resume failed", exc_info=True)
        self.emit("queue_updated", self.statut())
        return True

    def deplacer(self, from_index: int, to_index: int) -> bool:
        try:
            from_index, to_index = int(from_index), int(to_index)
        except (TypeError, ValueError):
            return False
        with self._state_lock:
            items = list(self._queue)
            if not (0 <= from_index < len(items) and 0 <= to_index < len(items)):
                return False
            if from_index != to_index:
                items.insert(to_index, items.pop(from_index))
                self._queue = deque(items)
        self._persist_queue()
        self.emit("queue_updated", self.statut())
        return True

    def retirer(self, index: int) -> bool:
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        with self._state_lock:
            items = list(self._queue)
            if not (0 <= index < len(items)):
                return False
            del items[index]
            self._queue = deque(items)
        self._persist_queue()
        self.emit("queue_updated", self.statut())
        return True

    def _start_worker(self) -> None:
        with self._state_lock:
            if self._task is not None and not self._task.done():
                return
            try:
                self._loop = asyncio.get_running_loop()
                self._cancelled.clear()
                self._task = asyncio.create_task(self._run())
            except RuntimeError:
                log.error("cannot start worker outside an event loop", exc_info=True)
                self._task = None
                self._loop = None

    async def _run(self) -> None:
        from engine.download.worker import traiter_item
        from engine.observability.context import set_task_id

        set_task_id("")
        while True:
            with self._state_lock:
                item = self._queue.popleft() if self._queue else None
            if item is None:
                break
            self._save_current(item)
            self._persist_queue()

            interrupted = False
            try:
                with self._state_lock:
                    self._current = item
                    self._started_at = time.time()
                    self._cancelled.clear()
                self.emit("queue_updated", self.statut())

                while self._paused.is_set():
                    await asyncio.sleep(0.5)
                await traiter_item(item, self)
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling() > 0 and not self._cancelled.is_cancelled():
                    interrupted = True
                    raise
                if task is not None:
                    task.uncancel()
                self.emit("dl_annule", {"nom": item.get("nom", "?")})
                try:
                    from engine.observability.metrics import metrics
                    metrics.incr("items_annules", 1)
                except Exception:
                    log.debug("metrics update failed (items_annules)", exc_info=True)
            except Exception as exc:
                log.exception("worker error")
                self.emit("dl_erreur", {"nom": item.get("nom", "?"), "erreur": str(exc)[:200]})
                try:
                    from engine.observability.metrics import metrics
                    metrics.incr("items_erreur", 1)
                except Exception:
                    log.debug("metrics update failed (items_erreur)", exc_info=True)
            finally:
                preserve = interrupted or self._preserve_on_stop
                self._preserve_on_stop = False
                if not preserve:
                    self._clear_current()
                self._persist_queue()
                with self._state_lock:
                    duree = (time.time() - self._started_at) if self._started_at else 0.0
                    self._current = None
                    self._started_at = None
                    if len(self._history) > HISTORY_MAX:
                        del self._history[:-HISTORY_MAX]
                self._cancelled.clear()
                if not preserve:
                    try:
                        from engine.observability.metrics import metrics
                        metrics.incr("temps_total_ms", int(duree * 1000))
                        metrics.incr("items_termines", 1)
                        log.info(metrics.resume_court())
                    except Exception:
                        log.debug("metrics update failed (items_termines)", exc_info=True)
                self.emit("queue_updated", self.statut())

queue = DownloadQueue()
