import asyncio
import logging
import os
import ssl
import threading
import time
from urllib.parse import urlparse

import requests as req

from engine.config.settings import DEFAULT_USER_AGENT as USER_AGENT
from engine.observability.redact import redact_url
from engine.scraping.site.animessama import SITE_DOMAIN, SITE_URL

log = logging.getLogger("engine.scraping.http_client")

HTTP_TIMEOUT = 20
HTTP_RETRIES = 2
RETRY_DELAY = 1.5
SESSION_CACHE_MAX = 8
HTTP_MAX_RESPONSE_SIZE = 10 * 1024 * 1024
HTTP_BODY_DEADLINE = 60
HTTP_TOTAL_DEADLINE = 180
_HTTP_ASYNC = os.getenv("HTTP_ASYNC", "").strip().lower() in ("1", "true", "yes")

def _is_safe_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if url == "/catalogue" or url.startswith("/catalogue/") or url.startswith("/catalogue?"):
        return True
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    return host == SITE_DOMAIN or host.endswith("." + SITE_DOMAIN)

_session_cache: dict[str, req.Session] = {}
_session_keys_order: list[str] = []
_session_lock = threading.Lock()

def _cookies_cache_key(cookies: list) -> str:
    import hashlib
    if not cookies:
        return "anonymous"
    parts = sorted(
        f"{c.get('name','')}={c.get('value','')}"
        for c in cookies
        if isinstance(c, dict) and c.get("name")
    )
    return hashlib.sha1("|".join(parts).encode()).hexdigest()

def clear_session_cache() -> None:
    with _session_lock:
        sessions = list(_session_cache.values())
        _session_cache.clear()
        _session_keys_order.clear()
    for s in sessions:
        try:
            s.close()
        except Exception:
            pass
    _client = _async_client_state.get("client")
    if _client is not None:
        try:
            _client.cookies.clear()
        except Exception:
            pass
    log.debug("Cache sessions HTTP vidé")

def _build_session(cookies: list) -> req.Session:
    s = req.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": SITE_URL + "/",
    })
    try:
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    except Exception as e:
        log.debug(f"_build_session : HTTPAdapter non configuré ({e})")
    for c in (cookies or []):
        if isinstance(c, dict) and c.get("name") and c.get("value"):
            s.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
            )
    return s

def _get_session(cookies: list) -> req.Session:
    key = _cookies_cache_key(cookies)
    with _session_lock:
        if key in _session_cache:
            try:
                _session_keys_order.remove(key)
            except ValueError:
                pass
            _session_keys_order.append(key)
            return _session_cache[key]

        while len(_session_cache) >= SESSION_CACHE_MAX and _session_keys_order:
            oldest_key = _session_keys_order.pop(0)
            evicted = _session_cache.pop(oldest_key, None)
            if evicted:
                try:
                    evicted.close()
                except Exception:
                    pass
                log.debug(f"Session HTTP évincée (cache plein) : {oldest_key[:12]}...")

        s = _build_session(cookies)
        _session_cache[key] = s
        _session_keys_order.append(key)
        return s

def _lire_corps_borne(r: req.Response, url: str) -> bytes | None:
    total = 0
    chunks: list[bytes] = []
    deadline = time.monotonic() + HTTP_BODY_DEADLINE
    try:
        for chunk in r.iter_content(64 * 1024):
            if time.monotonic() > deadline:
                log.warning(
                    f"_http_get({redact_url(url, 60)}) : corps trop lent "
                    f"(> {HTTP_BODY_DEADLINE}s) — abandon"
                )
                return None
            if not chunk:
                continue
            total += len(chunk)
            if total > HTTP_MAX_RESPONSE_SIZE:
                log.warning(
                    f"_http_get({redact_url(url, 60)}) : réponse trop grande "
                    f"(> {HTTP_MAX_RESPONSE_SIZE // 1024} Ko) — abandon"
                )
                return None
            chunks.append(chunk)
    except req.exceptions.RequestException as e:
        log.debug(f"_lire_corps_borne({redact_url(url, 60)}) : {e}")
        return None
    return b"".join(chunks)

def _reinjecter_corps_lu_en_streaming(r: req.Response, body: bytes) -> req.Response:
    r._content = body
    r._content_consumed = True
    r.encoding = "utf-8"
    return r

def _http_get(session: req.Session, url: str) -> req.Response | None:
    if url.startswith("/"):
        url = SITE_URL + url
    ERREURS_PERMANENTES = {403, 404, 410}

    started = time.monotonic()
    for attempt in range(HTTP_RETRIES + 1):
        if time.monotonic() - started > HTTP_TOTAL_DEADLINE:
            log.warning(
                f"_http_get({redact_url(url, 60)}) : budget total dépassé "
                f"(> {HTTP_TOTAL_DEADLINE}s) — abandon"
            )
            return None
        try:
            r = session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True, stream=True)

            content_length = r.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > HTTP_MAX_RESPONSE_SIZE:
                        log.warning(
                            f"_http_get({redact_url(url, 60)}) : réponse trop grande "
                            f"({int(content_length) // 1024} Ko > "
                            f"{HTTP_MAX_RESPONSE_SIZE // 1024} Ko) — abandon"
                        )
                        r.close()
                        return None
                except ValueError:
                    pass

            if r.ok:
                body = _lire_corps_borne(r, url)
                r.close()
                if body is None:
                    return None
                return _reinjecter_corps_lu_en_streaming(r, body)

            r.close()

            if r.status_code in ERREURS_PERMANENTES:
                log.debug(f"_http_get({redact_url(url, 60)}) : {r.status_code} permanent — abandon")
                return None

            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After", "")
                try:
                    wait = float(retry_after)
                    wait = max(1.0, min(wait, 120.0))
                    log.debug(f"429 — attente Retry-After={wait:.0f}s")
                except (ValueError, TypeError):
                    wait = RETRY_DELAY * 3
                if attempt < HTTP_RETRIES:
                    time.sleep(wait)
            elif attempt < HTTP_RETRIES:
                time.sleep(RETRY_DELAY)

        except req.exceptions.SSLError as e:
            log.warning(f"_http_get({redact_url(url, 60)}) : erreur SSL — {e}")
            return None
        except req.exceptions.ConnectionError as e:
            if attempt < HTTP_RETRIES:
                log.debug(f"_http_get({redact_url(url, 60)}) : connexion refusée (tentative {attempt+1}) — {e}")
                time.sleep(RETRY_DELAY)
            else:
                log.debug(f"_http_get({redact_url(url, 60)}) : {e}")
        except req.exceptions.Timeout:
            if attempt < HTTP_RETRIES:
                log.debug(f"_http_get({redact_url(url, 60)}) : timeout (tentative {attempt+1})")
                time.sleep(RETRY_DELAY)
            else:
                log.warning(f"_http_get({redact_url(url, 60)}) : timeout après {HTTP_RETRIES+1} tentatives")
        except req.exceptions.RequestException as e:
            if attempt < HTTP_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                log.debug(f"_http_get({redact_url(url, 60)}) : {e}")
    return None

class _AsyncResp:
    __slots__ = ("status_code", "text")

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

_async_client_state: dict = {"client": None, "loop": None}

def _cookies_dict(cookies) -> dict:
    out: dict = {}
    for c in cookies or []:
        if isinstance(c, dict) and c.get("name") and c.get("value") is not None:
            out[c["name"]] = c["value"]
    return out

async def _get_async_client():
    try:
        import httpx
    except ImportError:
        return None
    loop = asyncio.get_running_loop()
    st = _async_client_state
    if st["client"] is None or st["loop"] is not loop:
        old = st["client"]
        st["client"] = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Referer": SITE_URL + "/",
            },
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        st["loop"] = loop
        if old is not None:
            try:
                await old.aclose()
            except Exception:
                pass
    return st["client"]

async def close_async_client() -> None:
    st = _async_client_state
    client = st["client"]
    st["client"] = None
    st["loop"] = None
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass

async def _http_get_async(url: str, cookies):
    import httpx
    if url.startswith("/"):
        url = SITE_URL + url
    client = await _get_async_client()
    if client is None:
        return None
    ck = _cookies_dict(cookies)
    erreurs_permanentes = {403, 404, 410}
    started = time.monotonic()
    for attempt in range(HTTP_RETRIES + 1):
        if time.monotonic() - started > HTTP_TOTAL_DEADLINE:
            log.warning(
                f"_http_get_async({redact_url(url, 60)}) : budget total dépassé "
                f"(> {HTTP_TOTAL_DEADLINE}s) — abandon"
            )
            return None
        try:
            async with client.stream("GET", url, cookies=ck) as r:
                cl = r.headers.get("Content-Length")
                if cl:
                    try:
                        if int(cl) > HTTP_MAX_RESPONSE_SIZE:
                            return None
                    except ValueError:
                        pass
                if r.is_success:
                    total = 0
                    chunks: list[bytes] = []
                    deadline = time.monotonic() + HTTP_BODY_DEADLINE
                    async for chunk in r.aiter_bytes(64 * 1024):
                        if time.monotonic() > deadline:
                            log.warning(f"_http_get_async({redact_url(url, 60)}) : corps trop lent — abandon")
                            return None
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > HTTP_MAX_RESPONSE_SIZE:
                            return None
                        chunks.append(chunk)
                    return _AsyncResp(r.status_code, b"".join(chunks).decode("utf-8", "replace"))
                if r.status_code in erreurs_permanentes:
                    return None
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After", "")
                    try:
                        wait = max(1.0, min(float(retry_after), 120.0))
                    except (ValueError, TypeError):
                        wait = RETRY_DELAY * 3
                    if attempt < HTTP_RETRIES:
                        await asyncio.sleep(wait)
                elif attempt < HTTP_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
        except httpx.TimeoutException:
            if attempt < HTTP_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                log.warning(f"_http_get_async({redact_url(url, 60)}) : timeout")
        except httpx.ConnectError as e:
            if isinstance(getattr(e, "__cause__", None), ssl.SSLError):
                log.warning(f"_http_get_async({redact_url(url, 60)}) : erreur SSL — {e}")
                return None
            if attempt < HTTP_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                log.debug(f"_http_get_async({redact_url(url, 60)}) : {e}")
        except httpx.HTTPError as e:
            if attempt < HTTP_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                log.debug(f"_http_get_async({redact_url(url, 60)}) : {e}")
    return None

async def http_get(url: str, cookies):
    if _HTTP_ASYNC:
        try:
            import httpx  # noqa: F401
        except ImportError:
            pass
        else:
            return await _http_get_async(url, cookies)
    session = _get_session(cookies)
    return await asyncio.to_thread(_http_get, session, url)

_POST_HEADERS = {"X-Requested-With": "XMLHttpRequest"}

def _http_post(session: req.Session, url: str, data: dict) -> req.Response | None:
    if url.startswith("/"):
        url = SITE_URL + url
    erreurs_permanentes = {403, 404, 410}

    started = time.monotonic()
    for attempt in range(HTTP_RETRIES + 1):
        if time.monotonic() - started > HTTP_TOTAL_DEADLINE:
            log.warning(f"_http_post({redact_url(url, 60)}) : budget total dépassé — abandon")
            return None
        try:
            r = session.post(
                url, data=data, headers=_POST_HEADERS,
                timeout=HTTP_TIMEOUT, allow_redirects=True, stream=True,
            )
            content_length = r.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > HTTP_MAX_RESPONSE_SIZE:
                        r.close()
                        return None
                except ValueError:
                    pass

            if r.ok:
                body = _lire_corps_borne(r, url)
                r.close()
                if body is None:
                    return None
                return _reinjecter_corps_lu_en_streaming(r, body)

            r.close()
            if r.status_code in erreurs_permanentes:
                return None
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After", "")
                try:
                    wait = max(1.0, min(float(retry_after), 120.0))
                except (ValueError, TypeError):
                    wait = RETRY_DELAY * 3
                if attempt < HTTP_RETRIES:
                    time.sleep(wait)
            elif attempt < HTTP_RETRIES:
                time.sleep(RETRY_DELAY)
        except req.exceptions.SSLError as e:
            log.warning(f"_http_post({redact_url(url, 60)}) : erreur SSL — {e}")
            return None
        except req.exceptions.Timeout:
            if attempt < HTTP_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                log.warning(f"_http_post({redact_url(url, 60)}) : timeout")
        except req.exceptions.RequestException as e:
            if attempt < HTTP_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                log.debug(f"_http_post({redact_url(url, 60)}) : {e}")
    return None

async def _http_post_async(url: str, cookies, data: dict):
    import httpx
    if url.startswith("/"):
        url = SITE_URL + url
    client = await _get_async_client()
    if client is None:
        return None
    ck = _cookies_dict(cookies)
    erreurs_permanentes = {403, 404, 410}
    started = time.monotonic()
    for attempt in range(HTTP_RETRIES + 1):
        if time.monotonic() - started > HTTP_TOTAL_DEADLINE:
            log.warning(f"_http_post_async({redact_url(url, 60)}) : budget total dépassé — abandon")
            return None
        try:
            async with client.stream("POST", url, data=data, cookies=ck, headers=_POST_HEADERS) as r:
                cl = r.headers.get("Content-Length")
                if cl:
                    try:
                        if int(cl) > HTTP_MAX_RESPONSE_SIZE:
                            return None
                    except ValueError:
                        pass
                if r.is_success:
                    total = 0
                    chunks: list[bytes] = []
                    deadline = time.monotonic() + HTTP_BODY_DEADLINE
                    async for chunk in r.aiter_bytes(64 * 1024):
                        if time.monotonic() > deadline:
                            return None
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > HTTP_MAX_RESPONSE_SIZE:
                            return None
                        chunks.append(chunk)
                    return _AsyncResp(r.status_code, b"".join(chunks).decode("utf-8", "replace"))
                if r.status_code in erreurs_permanentes:
                    return None
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After", "")
                    try:
                        wait = max(1.0, min(float(retry_after), 120.0))
                    except (ValueError, TypeError):
                        wait = RETRY_DELAY * 3
                    if attempt < HTTP_RETRIES:
                        await asyncio.sleep(wait)
                elif attempt < HTTP_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
        except httpx.TimeoutException:
            if attempt < HTTP_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                log.warning(f"_http_post_async({redact_url(url, 60)}) : timeout")
        except httpx.ConnectError as e:
            if isinstance(getattr(e, "__cause__", None), ssl.SSLError):
                return None
            if attempt < HTTP_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                log.debug(f"_http_post_async({redact_url(url, 60)}) : {e}")
        except httpx.HTTPError as e:
            if attempt < HTTP_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            else:
                log.debug(f"_http_post_async({redact_url(url, 60)}) : {e}")
    return None

async def http_post(url: str, cookies, data: dict):
    if _HTTP_ASYNC:
        try:
            import httpx  # noqa: F401
        except ImportError:
            pass
        else:
            return await _http_post_async(url, cookies, data)
    session = _get_session(cookies)
    return await asyncio.to_thread(_http_post, session, url, data)
