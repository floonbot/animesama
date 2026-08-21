
import contextlib
import logging
import os
import zipfile
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import requests

from engine.config.settings import DEFAULT_USER_AGENT
from engine.domain.exceptions import DownloadCancelled, UnsafeUrlError
from engine.download._engine_utils import token_annule
from engine.observability.redact import redact_url
from engine.scraping.site.animessama import SITE_URL
from engine.utils import url_pin
from engine.utils.security import is_safe_url, pin_target, sanitize_filename

log = logging.getLogger("engine.download.scan_images")

IMG_TIMEOUT = 30
IMG_MAX_BYTES = 30 * 1024 * 1024
PAGE_RETRIES = 2
RETRY_DELAY = 1.0

_EXT_BY_CT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}

def _est_annule(cancelled) -> bool:
    return token_annule(cancelled)

def _ext_depuis(url: str, content_type: str) -> str:
    ext = _EXT_BY_CT.get((content_type or "").split(";")[0].strip().lower())
    if ext:
        return ext
    low = url.lower()
    for cand in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        if cand in low:
            return ".jpg" if cand == ".jpeg" else cand
    return ".jpg"

def _host_sur(url: str, cache: dict[str, bool]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    verdict = cache.get(host)
    if verdict is None:
        verdict = is_safe_url(url)
        cache[host] = verdict
    return verdict

def _telecharger_image(
    session: requests.Session, url: str, safe_cache: dict[str, bool] | None = None
) -> tuple[bytes, str] | None:
    safe = _host_sur(url, safe_cache) if safe_cache is not None else is_safe_url(url)
    if not safe:
        log.warning("scan: URL image non autorisée — %s", redact_url(url, 80))
        return None
    import time

    ctx: contextlib.AbstractContextManager[None]
    try:
        host, ip = pin_target(url)
    except UnsafeUrlError:
        log.warning("scan: URL image non autorisée (pin) — %s", redact_url(url, 80))
        return None
    except (LookupError, OSError, ValueError):
        ctx = contextlib.nullcontext()
    else:
        ctx = url_pin.pin_connection(host, ip)

    with ctx:
        for attempt in range(PAGE_RETRIES + 1):
            r = None
            try:
                r = session.get(url, timeout=IMG_TIMEOUT, stream=True, allow_redirects=False)
                sc = r.status_code
                if sc != 200:
                    r.close()
                    if sc in (301, 302, 303, 307, 308):
                        log.warning("scan: redirection refusée (SSRF) — %s", redact_url(url, 80))
                        return None
                    if 400 <= sc < 500 and sc != 429:
                        return None
                    if attempt < PAGE_RETRIES:
                        time.sleep(RETRY_DELAY)
                        continue
                    return None
                total = 0
                chunks: list[bytes] = []
                for chunk in r.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > IMG_MAX_BYTES:
                        log.warning("scan: image trop grande — %s", redact_url(url, 80))
                        r.close()
                        return None
                    chunks.append(chunk)
                ext = _ext_depuis(url, r.headers.get("Content-Type", ""))
                r.close()
                data = b"".join(chunks)
                if not data:
                    return None
                return data, ext
            except requests.exceptions.RequestException as e:
                if r is not None:
                    try:
                        r.close()
                    except OSError:
                        pass
                log.debug("scan image (essai %d) %s : %s", attempt + 1, redact_url(url, 60), e)
                if attempt < PAGE_RETRIES:
                    time.sleep(RETRY_DELAY)
            finally:
                if r is not None:
                    with contextlib.suppress(Exception):
                        r.close()
    return None

def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT, "Referer": SITE_URL + "/"})
    try:
        from requests.adapters import HTTPAdapter
        _adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=0)
        session.mount("https://", _adapter)
        session.mount("http://", _adapter)
    except Exception as e:
        log.debug("scan_download: HTTPAdapter non configuré (%s)", e)
    return session

def _ecrire_cbz_chapitre(
    session: requests.Session,
    pages: list[dict],
    chap: str,
    cbz_path: str,
    faits: int,
    total_chaps: int,
    cancelled: Any,
    on_progress: Callable[[int, str], None] | None,
    safe_cache: dict[str, bool],
) -> None:
    cbz_partiel = cbz_path + ".part"
    nb_pages = len(pages)
    try:
        with zipfile.ZipFile(cbz_partiel, "w", zipfile.ZIP_STORED) as zf:
            for pi, p in enumerate(pages):
                if _est_annule(cancelled):
                    raise DownloadCancelled()
                res = _telecharger_image(session, p["url"], safe_cache)
                if res is None:
                    raise RuntimeError(
                        f"page {p.get('page', pi + 1)} du chapitre {chap} introuvable"
                    )
                data, ext = res
                try:
                    num_page = int(p.get("page", pi + 1))
                except (TypeError, ValueError):
                    num_page = pi + 1
                zf.writestr(f"{num_page:03d}{ext}", data)
                if on_progress:
                    pct = round((faits + (pi + 1) / nb_pages) / total_chaps * 100)
                    on_progress(pct, f"Chapitre {chap} — page {pi + 1}/{nb_pages}")
        os.replace(cbz_partiel, cbz_path)
    except BaseException:
        try:
            if os.path.exists(cbz_partiel):
                os.remove(cbz_partiel)
        except OSError:
            pass
        raise

def scan_download(
    oeuvre: str,
    lang: str,
    chapitres: list[str],
    dossier: str,
    cancelled: Any = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> str | None:
    from engine.scraping.scan import get_pages_sync

    try:
        os.makedirs(dossier, exist_ok=True)
    except OSError as e:
        log.error("scan: dossier impossible à créer '%s' : %s", dossier, e)
        return None

    session = _build_session()

    total_chaps = len(chapitres) or 1
    dernier: str | None = None
    faits = 0
    safe_cache: dict[str, bool] = {}

    try:
        for chap in chapitres:
            if _est_annule(cancelled):
                raise DownloadCancelled()

            # `chap` sert de cle a l'API du site : on le garde intact pour la
            # requete et on n'assainit que le nom de fichier. Sans ca un chapitre
            # portant un separateur ecrit le .cbz hors du dossier de scans.
            cbz_path = os.path.join(dossier, f"Chapitre {sanitize_filename(chap)}.cbz")
            if os.path.exists(cbz_path):
                faits += 1
                dernier = cbz_path
                if on_progress:
                    on_progress(round(faits / total_chaps * 100), f"Chapitre {chap} déjà présent")
                continue

            pages = get_pages_sync(oeuvre, chap, lang)
            if not pages:
                log.warning("scan: aucune page pour chapitre %s (%s)", chap, oeuvre)
                faits += 1
                if on_progress:
                    on_progress(round(faits / total_chaps * 100), f"Chapitre {chap} ignoré")
                continue

            try:
                _ecrire_cbz_chapitre(
                    session, pages, chap, cbz_path, faits, total_chaps,
                    cancelled, on_progress, safe_cache,
                )
                dernier = cbz_path
            except DownloadCancelled:
                raise
            except Exception as e:
                log.warning("scan: chapitre %s ignoré (%s) — chapitre suivant", chap, e)
                if on_progress:
                    on_progress(round((faits + 1) / total_chaps * 100), f"Chapitre {chap} échoué")
            faits += 1
    finally:
        try:
            session.close()
        except Exception:
            pass

    return dernier
