
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from engine.config.settings import STATIC_DIR
from engine.observability.context import reset_task_id, set_task_id
from engine.version import APP_VERSION

log = logging.getLogger("web.api.app")

SSE_PATH = "/api/events"
STREAM_PATH = "/api/anime/stream"
COVER_PATH = "/api/anime/cover"
SCAN_IMG_PATH = "/api/anime/scan-local-img"
_NO_GZIP_PATHS = frozenset({SSE_PATH, STREAM_PATH, COVER_PATH, SCAN_IMG_PATH})

_DIAG_API_PATHS = frozenset({
    "/api/health", "/api/metrics", "/api/logs",
    "/api/download/metrics", "/api/download/breakers",
})

# Starlette compresse de maniere synchrone, sur la boucle asyncio. Au niveau 9
# (son defaut) une reponse de librairie de 350 Ko bloquait la boucle 11 ms ;
# au niveau 6 elle coute 3 ms pour 1 Ko de plus. L'app n'ecoute que sur la
# boucle locale : la bande passante est gratuite, le temps CPU non.
GZIP_LEVEL = 6

class GZipExceptSSE:

    def __init__(self, app, minimum_size: int = 500, compresslevel: int = GZIP_LEVEL) -> None:
        self.plain = app
        self.gzipped = GZipMiddleware(
            app, minimum_size=minimum_size, compresslevel=compresslevel
        )

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") in _NO_GZIP_PATHS:
            await self.plain(scope, receive, send)
        else:
            await self.gzipped(scope, receive, send)

CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: https:; "
    "media-src 'self' blob:; "
    "font-src 'self'; "
    "connect-src 'self' https://graphql.anilist.co"
)

_SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)

class SecurityHeaders:

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}
                for name, value in _SECURITY_HEADERS:
                    if name not in present:
                        headers.append((name, value))
            await send(message)

        await self.app(scope, receive, _send)

class RequestContext:

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = set_task_id(uuid.uuid4().hex[:6])
        try:
            await self.app(scope, receive, send)
        finally:
            reset_task_id(token)

class RequestMetrics:

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") != "http" or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        is_diag = path in _DIAG_API_PATHS
        is_media = path in _NO_GZIP_PATHS
        measure = not is_diag and not is_media
        status = {"code": 0}

        async def _send(message):
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status", 0)
            await send(message)

        start = time.monotonic() if measure else 0.0
        try:
            await self.app(scope, receive, _send)
        finally:
            try:
                from engine.observability.metrics import metrics
                if is_diag:
                    metrics.incr("http_requests_diag")
                elif is_media:
                    metrics.incr("http_requests_media")
                else:
                    metrics.incr("http_requests_total")
                    code = status["code"] or 500
                    if code >= 500:
                        metrics.incr("http_requests_5xx")
                    elif code >= 400:
                        metrics.incr("http_requests_4xx")
                    elif code >= 300:
                        metrics.incr("http_requests_3xx")
                    elif code >= 200:
                        metrics.incr("http_requests_2xx")
                    metrics.observe("lat_request_s", time.monotonic() - start)
            except Exception:
                log.debug("request metrics failed", exc_info=True)

class CachedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if response.status_code == 200:
            if ext in ("png", "jpg", "jpeg", "webp", "svg", "ico", "woff", "woff2"):
                response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
            elif ext in ("css", "js"):
                response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=86400"
            elif ext == "html":
                response.headers["Cache-Control"] = "public, max-age=60"
            else:
                response.headers["Cache-Control"] = "public, max-age=300"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = CSP
            response.headers["X-Frame-Options"] = "DENY"
        return response

@asynccontextmanager
async def lifespan(app: FastAPI):
    from web.api.routes.sse import capture_loop_at_startup
    capture_loop_at_startup()

    try:
        import asyncio as _asyncio

        from engine.download.queue import queue
        await _asyncio.to_thread(queue.enable_persistence)
        queue.resume_pending()
    except Exception as e:
        log.warning(f"Persistance des téléchargements : {e}")

    try:
        import threading

        from engine.download.methods.nm3u8dl import purge_stale_tmp_dirs
        threading.Thread(target=purge_stale_tmp_dirs, daemon=True, name="tmp-sweep").start()
    except Exception as e:
        log.debug(f"Nettoyage des dossiers de reprise : {e}")

    try:
        from engine.download.methods._ytdlp_updater import demarrer_verification_ytdlp
        demarrer_verification_ytdlp()
    except Exception as e:
        log.debug(f"yt-dlp auto-update : {e}")

    try:
        import asyncio as _asyncio

        from engine.download.interceptor import get_browser

        async def _warm_browser():
            try:
                await get_browser()
            except Exception as e:
                log.warning(
                    "Démarrage navigateur : Chromium indisponible (%s). Les hôtes connus "
                    "restent téléchargeables via yt-dlp ; vudeo et les hôtes inconnus le requièrent.",
                    e,
                )

        app.state._browser_warm = _asyncio.create_task(_warm_browser())
    except Exception as e:
        log.warning(f"Démarrage navigateur : {e}")

    yield

    try:
        import asyncio as _asyncio

        from web.api.routes.sse import signal_shutdown
        signal_shutdown()
        await _asyncio.sleep(0.1)
    except Exception as e:
        log.debug(f"[shutdown] signal_shutdown : {e}")
    try:
        from engine.download.queue import queue
        queue._cancel_task_threadsafe()
        await _asyncio.sleep(0.1)
    except Exception as e:
        log.debug(f"[shutdown] cancel worker : {e}")
    try:
        from engine.download.methods._proc_registry import kill_all_processes
        n = kill_all_processes()
        if n:
            log.info(f"[shutdown] {n} subprocess de téléchargement tué(s)")
    except Exception as e:
        log.debug(f"[shutdown] kill_all_processes : {e}")
    try:
        from engine.download.worker import shutdown as worker_shutdown
        worker_shutdown()
    except Exception as e:
        log.debug(f"[shutdown] worker_shutdown : {e}")
    try:
        from engine.auth.manager import auth_manager
        auth_manager.stop_keepalive_loop()
    except Exception as e:
        log.debug(f"[shutdown] stop_keepalive : {e}")
    try:
        warm = getattr(app.state, "_browser_warm", None)
        if warm is not None and not warm.done():
            warm.cancel()
            await _asyncio.gather(warm, return_exceptions=True)
    except Exception as e:
        log.debug(f"[shutdown] browser warm cancel : {e}")
    try:
        from engine.download.interceptor import fermer_browser
        await fermer_browser()
    except Exception as e:
        log.debug(f"[shutdown] fermer_browser : {e}")
    try:
        from engine.scraping.http_client import close_async_client
        await close_async_client()
    except Exception as e:
        log.debug(f"[shutdown] close_async_client : {e}")
    try:
        from engine.download.queue import queue
        if queue._store is not None:
            queue._store.close()
    except Exception as e:
        log.debug(f"[shutdown] store close : {e}")
    try:
        from engine.cache.cover_images import shutdown_covers
        shutdown_covers()
    except Exception as e:
        log.debug(f"[shutdown] shutdown_covers : {e}")
    # Les trois caches disque tiennent une connexion SQLite ouverte pour la duree
    # du processus, comme downloads.db juste au-dessus : ils se ferment pareil.
    for module, attribut in (
        ("engine.scraping.anilist", "_disk"),
        ("engine.scraping.episodes", "_ep_disk"),
        ("engine.scraping.scan", "_scan_disk"),
    ):
        try:
            import importlib
            getattr(importlib.import_module(module), attribut).close()
        except Exception as e:
            log.debug(f"[shutdown] close {module}.{attribut} : {e}")

def _build_cors_origins(host: str, port: int) -> list[str]:
    origins = [
        f"http://{host}:{port}",
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    ]
    return list(dict.fromkeys(origins))

def _build_allowed_hosts(host: str, port: int) -> frozenset[str]:
    base = {f"localhost:{port}", f"127.0.0.1:{port}", f"{host}:{port}",
            "localhost", "127.0.0.1", host}
    return frozenset(base)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

def _host_guard_factory(allowed_hosts: frozenset[str], allowed_origins: frozenset[str]):
    import json as _json
    from urllib.parse import urlparse as _urlparse

    async def _deny(send, status: int, erreur: str) -> None:
        body = _json.dumps({"ok": False, "erreur": erreur}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        })
        await send({"type": "http.response.body", "body": body})

    class HostGuard:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            host = (headers.get("host") or "").lower()
            if host not in allowed_hosts:
                await _deny(send, 421, "Host non autorisé")
                return

            if scope.get("method", "GET") not in _SAFE_METHODS:
                if headers.get("origin") is None and headers.get("referer") is None:
                    await _deny(send, 403, "En-tête Origin/Referer manquant (CSRF)")
                    return
                origin = headers.get("origin")
                if origin is None:
                    p = _urlparse(headers.get("referer", ""))
                    origin = f"{p.scheme}://{p.netloc}" if p.scheme else None
                if origin is None or origin not in allowed_origins:
                    await _deny(send, 403, "Origine non autorisée (CSRF)")
                    return

            await self.app(scope, receive, send)

    return HostGuard

async def _global_exception_handler(request, exc: Exception):
    import traceback

    from fastapi.responses import JSONResponse
    log.error(
        f"Exception non gérée {request.method} {request.url.path} : "
        f"{type(exc).__name__}: {exc}\n" + traceback.format_exc()
    )
    headers = {}
    origin = request.headers.get("origin")
    if origin and origin in getattr(request.app.state, "cors_origins", frozenset()):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    return JSONResponse(
        status_code=500,
        content={"erreur": "Une erreur interne est survenue.", "ok": False},
        headers=headers,
    )

def create_app() -> FastAPI:
    app = FastAPI(
        title="Anime Downloader",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    from engine.config.settings import HOST, PORT
    cors_origins = _build_cors_origins(HOST, PORT)
    app.state.cors_origins = frozenset(cors_origins)

    app.add_middleware(RequestMetrics)
    app.add_middleware(RequestContext)
    app.add_middleware(
        _host_guard_factory(
            _build_allowed_hosts(HOST, PORT),
            frozenset(cors_origins),
        )
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    app.add_middleware(GZipExceptSSE, minimum_size=500)
    app.add_middleware(SecurityHeaders)
    app.add_exception_handler(Exception, _global_exception_handler)

    from web.api.routes.sse import connect_queue
    connect_queue()
    _register_routes(app)
    app.mount("/", CachedStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app

def _register_routes(app: FastAPI) -> None:
    from web.api.routes.anime import router as anime_router
    from web.api.routes.auth import router as auth_router
    from web.api.routes.download import router as download_router
    from web.api.routes.health import router as health_router
    from web.api.routes.settings import router as settings_router
    from web.api.routes.sse import router as sse_router

    app.include_router(auth_router,     prefix="/api/auth",     tags=["auth"])
    app.include_router(anime_router,    prefix="/api/anime",    tags=["anime"])
    app.include_router(download_router, prefix="/api/download", tags=["download"])
    app.include_router(sse_router,      prefix="/api",          tags=["events"])
    app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
    app.include_router(health_router,   prefix="/api",          tags=["health"])
