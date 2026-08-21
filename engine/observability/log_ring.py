import logging
import threading
from collections import deque

from engine.observability.context import get_task_id
from engine.observability.redact import redact_text

RING_CAPACITY = 400

_LEVEL_NUMS = {
    "DEBUG": 10, "INFO": 20, "OK": 25, "WARNING": 30, "WARN": 30,
    "ERROR": 40, "CRITICAL": 50,
}


def level_threshold(name: str) -> int:
    return _LEVEL_NUMS.get((name or "").strip().upper(), 0)


class RingBufferHandler(logging.Handler):
    """In-memory ring of the most recent log records, exposed by `/api/logs`.

    Stores only structured, log-safe fields (timestamp, level, logger name, task
    id, already-rendered message). No exception traceback is kept, and messages
    are the same secret-free strings emitted to the console (URLs redacted,
    cookies never logged), so the buffer never holds a secret.
    """

    def __init__(self, capacity: int = RING_CAPACITY) -> None:
        super().__init__()
        self._buf: deque[dict] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": record.created,
                "level": record.levelname,
                "levelno": record.levelno,
                "logger": record.name,
                "tid": get_task_id(),
                "msg": redact_text(record.getMessage()),
            }
        except Exception:
            return
        with self._lock:
            self._buf.append(entry)

    def snapshot(
        self, limit: int | None = None, tid: str = "", min_levelno: int = 0
    ) -> list[dict]:
        with self._lock:
            items = list(self._buf)
        if tid:
            items = [e for e in items if e["tid"] == tid]
        if min_levelno > 0:
            items = [e for e in items if e.get("levelno", 0) >= min_levelno]
        if limit is not None and limit >= 0:
            items = items[-limit:] if limit else []
        return items

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


log_ring = RingBufferHandler()


def install() -> None:
    root = logging.getLogger()
    if log_ring not in root.handlers:
        root.addHandler(log_ring)
