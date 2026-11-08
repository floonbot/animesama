import asyncio
import logging
import os
import platform
import shutil
import sys
import tempfile

from fastapi import APIRouter

from engine.version import APP_VERSION, identite_build

try:
    import psutil as _psutil
    _PROC = _psutil.Process()
except Exception:
    _psutil = None
    _PROC = None

router = APIRouter()
log = logging.getLogger("web.api.health")

def _disk_info(path) -> dict:
    u = shutil.disk_usage(str(path))
    return {
        # Le chemin resolu, pas celui des reglages : quand le dossier configure
        # est injoignable, get_downloads_dir retombe sur le defaut et c'est ici
        # seulement que la difference se voit.
        "path": os.path.abspath(str(path)),
        "drive": os.path.splitdrive(os.path.abspath(str(path)))[0] or "/",
        "free_gb": round(u.free / 1024 ** 3, 2),
        "total_gb": round(u.total / 1024 ** 3, 2),
        "used_pct": round(u.used / u.total * 100) if u.total else 0,
    }

def _health_queue() -> dict | None:
    try:
        from engine.download.queue import queue
        st = queue.statut()
        return {
            "en_cours": bool(st.get("en_cours")),
            "pending": len(st.get("queue", [])),
            "en_pause": bool(st.get("en_pause")),
            "persistence": queue._store is not None,
        }
    except Exception:
        log.debug("health: queue", exc_info=True)
        return None

def _health_auth() -> dict | None:
    try:
        from engine.auth.manager import auth_manager
        keepalive = False
        try:
            t = auth_manager._keepalive_thread
            keepalive = bool(t and t.is_alive())
        except Exception:
            log.debug("health: keepalive", exc_info=True)
        return {
            "connected": auth_manager.is_logged_in,
            "cookies": len(auth_manager.cookies or []),
            "keepalive": keepalive,
        }
    except Exception:
        log.debug("health: auth", exc_info=True)
        return None

def _health_engines() -> dict | None:
    try:
        from engine.download.methods.ffmpeg_engine import _get_ffmpeg_path
        from engine.download.methods.nm3u8dl import _get_nm3u8dl_path
        from engine.download.methods.ytdlp_engine import _get_ytdlp_path
        return {
            "nm3u8dl": bool(_get_nm3u8dl_path()),
            "ytdlp": bool(_get_ytdlp_path()),
            "ffmpeg": bool(_get_ffmpeg_path()),
        }
    except Exception:
        log.debug("health: engines", exc_info=True)
        return None

def _health_breakers() -> dict | None:
    try:
        from engine.download._host_breakers import etat_breakers
        from engine.download._hotes_bloques import hotes_bloques
        etats = etat_breakers()
        return {
            "open": sorted(h for h, s in etats.items() if s == "open"),
            "half_open": sorted(h for h, s in etats.items() if s == "half_open"),
            # Refus de l'adresse IP (403 « administrative rules ») : ecartes 6 h.
            "bloques": hotes_bloques(),
        }
    except Exception:
        log.debug("health: breakers", exc_info=True)
        return None

def _runtime_chromium_bundled() -> bool:
    try:
        from engine.config.settings import bundled_chromium_present
        return bundled_chromium_present()
    except Exception:
        log.debug("health: chromium bundled probe", exc_info=True)
        return False

def _health_runtime() -> dict:
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "chromium_bundled": _runtime_chromium_bundled(),
        "playwright_browsers_path": os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
    }

def _health_build() -> dict:
    try:
        return identite_build()
    except Exception:
        log.debug("health: build", exc_info=True)
        return {"version": APP_VERSION, "source": "inconnu"}

def _health_sse() -> dict | None:
    try:
        from web.api.routes import sse as sse_mod
        return {"clients": len(sse_mod._listeners)}
    except Exception:
        log.debug("health: sse", exc_info=True)
        return None

@router.get("/health")
async def health():
    out: dict = {"ok": True, "version": APP_VERSION, "build": _health_build()}

    q = _health_queue()
    if q is not None:
        out["queue"] = q

    a = _health_auth()
    if a is not None:
        out["auth"] = a

    e = _health_engines()
    if e is not None:
        out["engines"] = e

    b = _health_breakers()
    if b is not None:
        out["breakers"] = b

    try:
        from engine.download import interceptor
        out["browser"] = interceptor._is_browser_alive(interceptor._browser)
    except Exception:
        log.debug("health: browser", exc_info=True)

    out["runtime"] = _health_runtime()

    out["disk"] = {}
    try:
        from engine.config.settings import get_downloads_dir, get_scans_dir
        for label, getter in (
            ("downloads", get_downloads_dir),
            ("scans", get_scans_dir),
            ("temp", tempfile.gettempdir),
        ):
            try:
                out["disk"][label] = await asyncio.to_thread(_disk_info, getter())
            except Exception:
                log.debug("health: disk %s", label, exc_info=True)
    except Exception:
        log.debug("health: disk", exc_info=True)

    uptime = 0
    try:
        from engine.observability.metrics import metrics
        uptime = metrics.uptime_s()
    except Exception:
        log.debug("health: uptime", exc_info=True)
    out["process"] = {
        "pid": os.getpid(),
        "python": platform.python_version(),
        "platform": sys.platform,
        "uptime_s": uptime,
    }
    if _PROC is not None:
        try:
            out["process"]["memory_mb"] = round(_PROC.memory_info().rss / 1024 / 1024, 1)
            out["process"]["threads"] = _PROC.num_threads()
            out["process"]["cpu_pct"] = round(_PROC.cpu_percent(interval=None), 1)
        except Exception:
            log.debug("health: psutil process", exc_info=True)

    s = _health_sse()
    if s is not None:
        out["sse"] = s

    return out

@router.get("/metrics")
async def metrics_alias():
    from web.api.routes.download import metriques

    return await metriques()

@router.get("/logs")
async def logs(limit: int = 200, tid: str = "", level: str = ""):
    from engine.observability.log_ring import level_threshold, log_ring
    n = max(1, min(int(limit), 500))
    entries = log_ring.snapshot(limit=n, tid=tid or "", min_levelno=level_threshold(level))
    return {"ok": True, "count": len(entries), "logs": entries}
