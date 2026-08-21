import asyncio
import logging
import re
import threading
import time

from engine.utils.aio import LoopLocal, loop_local_lock

log = logging.getLogger("engine.scraping.cache")

def _ll_locked(ll) -> bool:
    try:
        obj = getattr(ll, "_obj", None)
        return obj is not None and obj.locked()
    except Exception:
        return True

FAV_CACHE_TTL = 300
EP_CACHE_TTL = 600
EP_CACHE_MAX = 150
EP_LOCKS_MAX = 256

class ScraperCache:
    def __init__(self) -> None:
        self._fav: list = []
        self._fav_ts: float = 0.0
        self._ep: dict[str, tuple[dict, float]] = {}
        self._fav_lock = loop_local_lock()
        self._ep_locks: dict[str, LoopLocal[asyncio.Lock]] = {}
        self._ep_locks_guard = threading.Lock()

    def fav_lock(self):
        return self._fav_lock.get()

    def ep_lock(self, key: str):
        with self._ep_locks_guard:
            ll = self._ep_locks.get(key)
            if ll is None:
                if len(self._ep_locks) >= EP_LOCKS_MAX:
                    self._purge_ep_locks()
                ll = loop_local_lock()
                self._ep_locks[key] = ll
        return ll.get()

    def _purge_ep_locks(self) -> None:
        for k in [k for k, ll in self._ep_locks.items() if not _ll_locked(ll)]:
            self._ep_locks.pop(k, None)

    def fav_fresh(self) -> bool:
        return self._fav_ts > 0 and (time.time() - self._fav_ts) < FAV_CACHE_TTL

    def get_fav(self) -> list:
        return list(self._fav)

    def set_fav(self, data: list) -> None:
        self._fav = data
        self._fav_ts = time.time()

    def invalidate_fav(self) -> None:
        self._fav = []
        self._fav_ts = 0.0

    def get_ep(self, key: str) -> dict | None:
        entry = self._ep.get(key)
        if not entry:
            return None
        if (time.time() - entry[1]) >= EP_CACHE_TTL:
            self._ep.pop(key, None)
            return None
        return entry[0]

    def purge_ep_expired(self) -> int:
        now = time.time()
        old = [u for u, (_, ts) in self._ep.items() if now - ts >= EP_CACHE_TTL]
        for k in old:
            self._ep.pop(k, None)
        return len(old)

    def set_ep(self, key: str, data: dict) -> None:
        if len(self._ep) >= EP_CACHE_MAX:
            self.purge_ep_expired()
            if len(self._ep) >= EP_CACHE_MAX:
                for cle, _ in sorted(self._ep.items(), key=lambda x: x[1][1])[:20]:
                    self._ep.pop(cle, None)
        self._ep[key] = (data, time.time())

    def invalidate_ep(self, url: str | None = None) -> None:
        if url is None:
            self._ep.clear()
            return
        cache_key = url.split("?")[0].rstrip("/")
        self._ep.pop(cache_key, None)
        from engine.scraping.site.animessama import SITE_URL
        m = re.search(r"/catalogue/([^/?#]+)", url)
        if m:
            self._ep.pop(f"{SITE_URL}/catalogue/{m.group(1)}", None)

cache = ScraperCache()
