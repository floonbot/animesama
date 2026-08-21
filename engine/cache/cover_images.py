import contextlib
import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import requests

from engine.config.settings import DATA_DIR, DEFAULT_USER_AGENT
from engine.domain.exceptions import UnsafeUrlError
from engine.observability.redact import redact_url
from engine.utils import url_pin
from engine.utils.security import is_safe_url, pin_target

log = logging.getLogger("engine.cache.cover_images")

CACHE_DIR = DATA_DIR / "covers_cache"

def _preparer_cache_dir(d: Path) -> None:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning(
            "Cache des jaquettes indisponible (%s) — les couvertures seront "
            "retelechargees a chaque affichage.", e,
        )

_preparer_cache_dir(CACHE_DIR)

MAX_BYTES = 4 * 1024 * 1024
MAX_WIDTH = 360
MAX_PIXELS = 40_000_000
MAX_FILES = 2000
_EXT_BY_CT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

MAX_REDIRECTIONS = 2
NEG_TTL = 3600.0
NEG_MAX = 500

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cover")
_inflight: set[str] = set()
_inflight_lock = threading.Lock()
_echecs: dict[str, float] = {}

def _marquer_echec(url: str) -> None:
    with _inflight_lock:
        _echecs[url] = time.time() + NEG_TTL
        if len(_echecs) > NEG_MAX:
            maintenant = time.time()
            for u in [u for u, exp in _echecs.items() if exp <= maintenant]:
                del _echecs[u]
            # Rien n'avait encore expire : sans ce plafond dur, une librairie de
            # plusieurs milliers de covers cassees fait croitre le dict sans fin.
            surplus = len(_echecs) - NEG_MAX
            if surplus > 0:
                for u, _ in sorted(_echecs.items(), key=lambda kv: kv[1])[:surplus]:
                    del _echecs[u]

def _est_en_echec(url: str) -> bool:
    with _inflight_lock:
        expiration = _echecs.get(url)
        if expiration is None:
            return False
        if expiration <= time.time():
            del _echecs[url]
            return False
        return True

def vider_cache_negatif() -> None:
    with _inflight_lock:
        _echecs.clear()

def _executor_attendre() -> None:
    for _ in range(200):
        with _inflight_lock:
            if not _inflight:
                return
        time.sleep(0.01)

def shutdown_covers() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
    with _inflight_lock:
        _inflight.clear()
        _echecs.clear()

def _key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()

def cached_file(url: str) -> Path | None:
    base = CACHE_DIR / _key(url)
    for ext in (".jpg", ".png", ".webp", ".gif"):
        p = base.with_suffix(ext)
        if p.exists():
            return p
    return None

def _maybe_resize(data: bytes, ext: str) -> tuple[bytes, str]:
    try:
        import io

        from PIL import Image

        im: Image.Image = Image.open(io.BytesIO(data))
        if im.width * im.height > MAX_PIXELS:
            log.warning("cover: image %dx%d trop grande — non redimensionnée", im.width, im.height)
            return data, ext
        if im.width <= MAX_WIDTH:
            return data, ext
        h = int(im.height * (MAX_WIDTH / im.width))
        im = im.resize((MAX_WIDTH, h))
        if im.mode in ("RGBA", "P", "LA"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return buf.getvalue(), ".jpg"
    except Exception:
        return data, ext

def _requete_pinnee(url: str):
    ctx: contextlib.AbstractContextManager[None]
    try:
        host, ip = pin_target(url)
    except UnsafeUrlError:
        return None
    except (LookupError, OSError, ValueError):
        ctx = contextlib.nullcontext()
    else:
        ctx = url_pin.pin_connection(host, ip)
    with ctx:
        return requests.get(
            url,
            timeout=15,
            stream=True,
            allow_redirects=False,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )

def fetch_and_store(url: str) -> Path | None:
    cle_origine = url
    courante = url
    r = None
    try:
        for saut in range(MAX_REDIRECTIONS + 1):
            if not is_safe_url(courante):
                _marquer_echec(cle_origine)
                return None
            try:
                r = _requete_pinnee(courante)
            except requests.exceptions.RequestException as e:
                log.debug("cover fetch failed (%s): %s", redact_url(courante, 80), e)
                return None
            if r is None:
                _marquer_echec(cle_origine)
                return None
            if r.status_code not in (301, 302, 303, 307, 308):
                break
            cible = r.headers.get("Location") or ""
            r.close()
            r = None
            if not cible or saut == MAX_REDIRECTIONS:
                _marquer_echec(cle_origine)
                return None
            courante = urljoin(courante, cible)
        if r is None:
            _marquer_echec(cle_origine)
            return None
        ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not r.ok or ct not in _EXT_BY_CT:
            _marquer_echec(cle_origine)
            return None
        total = 0
        chunks: list[bytes] = []
        try:
            for c in r.iter_content(64 * 1024):
                total += len(c)
                if total > MAX_BYTES:
                    _marquer_echec(cle_origine)
                    return None
                chunks.append(c)
        except requests.exceptions.RequestException:
            return None
    finally:
        if r is not None:
            r.close()
    data, ext = _maybe_resize(b"".join(chunks), _EXT_BY_CT[ct])
    path = (CACHE_DIR / _key(url)).with_suffix(ext)
    try:
        tmp = path.with_suffix(ext + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as e:
        log.debug("cover store failed: %s", e)
        return None
    _evict_old_files()
    return path

def _evict_old_files() -> None:
    try:
        with os.scandir(CACHE_DIR) as it:
            entries = [e for e in it if e.is_file()]
        if len(entries) <= MAX_FILES:
            return
        entries.sort(key=lambda e: e.stat().st_mtime)
        for e in entries[: len(entries) - MAX_FILES]:
            try:
                Path(e.path).unlink()
            except OSError:
                pass
    except Exception as e:
        log.debug("cover cache eviction failed: %s", e)

def warm(url: str) -> None:
    if cached_file(url) or _est_en_echec(url):
        return
    with _inflight_lock:
        if url in _inflight:
            return
        _inflight.add(url)

    def _run() -> None:
        try:
            fetch_and_store(url)
        finally:
            with _inflight_lock:
                _inflight.discard(url)

    try:
        _executor.submit(_run)
    except RuntimeError:
        with _inflight_lock:
            _inflight.discard(url)
