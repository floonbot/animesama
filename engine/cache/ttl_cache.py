import threading
import time


class TTLCache:
    def __init__(self, ttl: float, name: str = "cache") -> None:
        self._ttl = ttl
        self._name = name
        self._value = None
        self._ts = 0.0
        self._has = False
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            hit = self._has and (time.time() - self._ts) < self._ttl
            value = self._value if hit else None
        try:
            from engine.observability.metrics import metrics
            metrics.incr(f"cache_hit_{self._name}" if hit else f"cache_miss_{self._name}")
        except Exception:
            pass
        return value

    def set(self, value) -> None:
        with self._lock:
            self._value = value
            self._ts = time.time()
            self._has = True

    def invalidate(self) -> None:
        with self._lock:
            self._value = None
            self._ts = 0.0
            self._has = False
