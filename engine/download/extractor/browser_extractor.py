
import asyncio
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from engine.config.settings import BROWSER_PAGE_TIMEOUT_MS
from engine.download._engine_utils import est_url_http as _est_url_http
from engine.download._patterns import (
    media_kind,
    url_a_ignorer,
    url_est_stream,
)
from engine.observability.redact import redact_text, redact_url

log = logging.getLogger("engine.download.extractor.browser_extractor")

_JS_HOOKS_PATH = Path(__file__).parent / "js_hooks.js"

def _normaliser(url: str) -> str:
    try:
        p = urlparse(url)
        return p._replace(fragment="").geturl()
    except Exception:
        return url

_js_hooks_cache: dict = {}


def clear_js_hooks_cache() -> None:
    _js_hooks_cache.clear()


def _charger_js_hooks() -> str:
    path = _JS_HOOKS_PATH
    cached = _js_hooks_cache.get(path)
    if cached is not None:
        return cached
    try:
        contenu = path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"Impossible de lire js_hooks.js : {e}")
        return ""
    _js_hooks_cache[path] = contenu
    return contenu

_SCORE_M3U8       = 100
_SCORE_MP4        = 40
_SCORE_DASH       = 40
_SCORE_MASTER     = 20
_SCORE_HLS_PATH   = 10
_SCORE_SECURE     = 5
_SCORE_CDP        = 30
_SCORE_FETCH_XHR  = 20
_SCORE_HLSJS      = 15
_SCORE_DOM        = 5
_SCORE_PERF       = 2

_CDP_HDRS_MAX     = 500

def _score_url(url: str, type_: str) -> int:
    score = 0
    low = url.lower()
    if ".m3u8" in low:        score += _SCORE_M3U8
    if ".txt" in low and media_kind(url) == "hls":  score += _SCORE_M3U8
    if ".mpd" in low:         score += _SCORE_DASH
    if ".mp4" in low:         score += _SCORE_MP4
    if "master" in low:       score += _SCORE_MASTER
    if "/hls" in low:         score += _SCORE_HLS_PATH
    if "/secure/" in low:     score += _SCORE_SECURE
    if type_ in ("cdp_request", "cdp_response"): score += _SCORE_CDP
    if type_ in ("fetch", "xhr"):                score += _SCORE_FETCH_XHR
    if type_ in ("hlsjs_loadSource",):           score += _SCORE_HLSJS
    if type_.startswith("dom"):                  score += _SCORE_DOM
    if type_.startswith("perf"):                 score += _SCORE_PERF
    return score

def _meilleur_resultat(all_results: list[dict]) -> dict | None:
    if not all_results:
        return None
    scored = sorted(
        all_results,
        key=lambda r: _score_url(r["url"], r.get("type", "")),
        reverse=True,
    )
    best = scored[0]
    if len(scored) > 1:
        log.debug(
            f"Meilleur flux (score {_score_url(best['url'], best.get('type',''))}) "
            f": {redact_url(best['url'], 80)}"
        )
    return best

_FORENSIC_M3U8_RE = re.compile(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', re.I)
_FORENSIC_JSON_RE = re.compile(r'"(https?://[^"]+\.m3u8[^"]*)"', re.I)
_FORENSIC_MEDIA_RE = re.compile(r'https?://[^\s\'"<>]+\.(?:mp4|mpd)[^\s\'"<>]*', re.I)

async def _forensic_scan(page) -> list[dict]:
    resultats = []
    try:
        html = await page.content()
        for m in _FORENSIC_M3U8_RE.finditer(html):
            url = m.group(0).rstrip("\\/")
            resultats.append({"url": url, "type": "forensic_html", "ts": 0})
        for m in _FORENSIC_JSON_RE.finditer(html):
            url = m.group(1)
            resultats.append({"url": url, "type": "forensic_json", "ts": 0})
        for m in _FORENSIC_MEDIA_RE.finditer(html):
            url = m.group(0).rstrip("\\/")
            resultats.append({"url": url, "type": "forensic_media", "ts": 0})
    except Exception as e:
        log.debug(f"forensic_scan : {e}")
    return resultats

async def _injecter_hooks_frame(frame, js_code: str) -> None:
    try:
        await frame.evaluate(js_code)
    except Exception as e:
        log.debug(f"injection frame {redact_url(frame.url, 60)} : {e}")

async def _lire_logs_frame(frame) -> list[dict]:
    try:
        raw = await frame.evaluate("window.__STREAM_LOGS__ || []")
        if isinstance(raw, list):
            return [e for e in raw if isinstance(e, dict)]
    except Exception as e:
        log.debug(f"lecture logs frame {redact_url(frame.url, 60)} : {e}")
    return []

PLAY_SELECTORS = (
    "video",
    ".vjs-big-play-button",
    "[class*='play-btn']",
    "[class*='playButton']",
    "[aria-label*='play' i]",
    ".plyr__control--overlaid",
)

async def _cliquer_play(page) -> None:
    for frame in list(page.frames)[:8]:
        for sel in PLAY_SELECTORS:
            try:
                await frame.click(sel, timeout=600)
                log.debug(f"clic play : {sel} (frame)")
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

async def _scanner_frames(page, js_code: str, ajouter) -> None:
    for frame in list(page.frames)[:8]:
        if frame == page.main_frame:
            continue
        if js_code:
            await _injecter_hooks_frame(frame, js_code)
        await asyncio.sleep(0.5)
        frame_logs = await _lire_logs_frame(frame)
        for entry in frame_logs:
            ajouter(entry.get("url", ""), entry.get("type", "frame"), source="iframe")

async def _scan_shadow_dom(page, ajouter) -> None:
    try:
        shadow_urls = await page.evaluate("""() => {
            const found = [];
            function scanShadow(root) {
                if (!root) return;
                const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (const el of all) {
                    if (el.shadowRoot) scanShadow(el.shadowRoot);
                    const src = el.src || el.getAttribute('data-src') || '';
                    if (src && (src.includes('.m3u8') || src.includes('/hls'))) found.push(src);
                }
            }
            scanShadow(document);
            return found;
        }""")
        for url in (shadow_urls or []):
            ajouter(url, "shadow_dom", source="shadow")
    except Exception as e:
        log.debug(f"shadow DOM scan : {e}")

def _construire_resultat(all_urls: dict[str, dict], timeline: list[dict]) -> dict:
    all_list = list(all_urls.values())
    best     = _meilleur_resultat(all_list)

    if best:
        log.info(f"Meilleur flux : {redact_url(best['url'], 100)}")
    else:
        log.warning("Aucun flux détecté")

    best_headers = {}
    if best:
        for t in timeline:
            if t["url"] == best["url"]:
                best_headers = t.get("headers", {})
                break

    return {
        "best":     {"url": best["url"], "headers": best_headers} if best else None,
        "all":      all_list,
        "timeline": timeline,
    }

def _brancher_cdp(cdp, cdp_hdrs: dict[str, dict], ajouter) -> None:
    def _on_cdp_request(params):
        try:
            url    = params.get("request", {}).get("url", "")
            hdrs   = params.get("request", {}).get("headers", {})
            req_id = params.get("requestId", "")
            if req_id:
                cdp_hdrs[req_id] = hdrs
                if len(cdp_hdrs) > _CDP_HDRS_MAX:
                    for _old in list(cdp_hdrs)[: len(cdp_hdrs) - _CDP_HDRS_MAX]:
                        cdp_hdrs.pop(_old, None)
            ajouter(url, "cdp_request", hdrs, source="cdp")
        except Exception:
            log.debug("cdp request handler error", exc_info=True)

    def _on_cdp_response(params):
        try:
            url      = params.get("response", {}).get("url", "")
            hdrs     = params.get("response", {}).get("headers", {})
            req_id   = params.get("requestId", "")
            req_hdrs = cdp_hdrs.pop(req_id, {})
            ajouter(url, "cdp_response", {**req_hdrs, **hdrs}, source="cdp")
        except Exception:
            log.debug("cdp response handler error", exc_info=True)

    cdp.on("Network.requestWillBeSent", _on_cdp_request)
    cdp.on("Network.responseReceived",  _on_cdp_response)

async def _executer_scans(
    page, mode: str, js_code: str, all_urls: dict[str, dict], ajouter
) -> None:
    logs_js = await _lire_logs_frame(page)
    for entry in logs_js:
        ajouter(entry.get("url", ""), entry.get("type", "js"), source="js")

    if mode != "fast" and not all_urls:
        await _scanner_frames(page, js_code, ajouter)

    if mode != "fast":
        await _scan_shadow_dom(page, ajouter)

    if mode == "forensic" or not all_urls:
        for entry in await _forensic_scan(page):
            ajouter(entry["url"], entry["type"], source="forensic")

async def _fermer_ressources(
    cdp, page, ctx, sem, sem_acquired: bool, erreur_grave: bool
) -> None:
    # Meme piege que interceptor._fermer_page_ctx, et le semaphore est le meme :
    # appelee depuis un finally, donc potentiellement pendant une annulation. Une
    # CancelledError levee par detach()/close() n'est pas rattrapee par
    # `except Exception` et emportait le permit. Quatre annulations pendant une
    # extraction forensic bloquaient ensuite toute interception Playwright.
    annulation: BaseException | None = None
    if cdp is not None:
        try:
            await cdp.detach()
        except asyncio.CancelledError as e:
            annulation = e
        except Exception as e:
            log.debug(f"cdp.detach() : {e}")
    for fermable, label in ((page, "page"), (ctx, "ctx")):
        if fermable is None:
            continue
        try:
            await fermable.close()
        except asyncio.CancelledError as e:
            annulation = e
        except Exception as e:
            log.debug(f"{label}.close() : {e}")
    if sem_acquired:
        sem.release()
    if annulation is not None:
        raise annulation
    if erreur_grave:
        try:
            from engine.download.interceptor import _reset_browser_apres_erreur
            await _reset_browser_apres_erreur()
        except Exception as e:
            log.debug(f"reset browser après erreur : {e}")

_EXTRACTION_MARGIN_S = 60.0

def _deadline_extraction(timeout: int) -> float:
    return BROWSER_PAGE_TIMEOUT_MS / 1000.0 + timeout + _EXTRACTION_MARGIN_S

async def extraire_flux(
    url_lecteur: str,
    timeout: int = 10,
    mode: str = "standard",
) -> dict:
    resultat_vide: dict = {"best": None, "all": [], "timeline": []}

    if not _est_url_http(url_lecteur):
        log.warning(f"URL invalide : {redact_url(url_lecteur, 80)}")
        return resultat_vide

    try:
        timeout = max(3, min(int(timeout or 10), 60))
    except (TypeError, ValueError):
        timeout = 10

    js_code   = _charger_js_hooks()
    all_urls:  dict[str, dict] = {}
    timeline:  list[dict]      = []
    cdp_hdrs:  dict[str, dict] = {}

    def _ajouter(url: str, type_: str, headers: dict | None = None, source: str = "js") -> None:
        url = _normaliser(url)
        if not url or url_a_ignorer(url) or not url_est_stream(url):
            return
        if url in all_urls:
            return
        entry = {"url": url, "type": type_, "ts": 0, "source": source}
        all_urls[url] = entry
        timeline.append({**entry, "headers": headers or {}})
        log.debug(f"[{type_}] {redact_url(url, 100)}")

    from engine.download.interceptor import (
        _ctx_semaphore,
        _nouveau_contexte,
        apply_stealth,
        get_browser,
    )
    from engine.scraping.site.animessama import SITE_URL

    ctx  = None
    page = None
    cdp  = None
    erreur_grave = False

    _sem = _ctx_semaphore()
    _sem_acquired = False
    try:
        async def _corps() -> None:
            nonlocal ctx, page, cdp, _sem_acquired
            if _sem is not None:
                await _sem.acquire()
                _sem_acquired = True
            browser = await get_browser()
            ctx = await _nouveau_contexte(browser, SITE_URL)
            if js_code:
                await ctx.add_init_script(js_code)
            page = await ctx.new_page()

            await apply_stealth(page)

            cdp = await ctx.new_cdp_session(page)
            await cdp.send("Network.enable")

            _brancher_cdp(cdp, cdp_hdrs, _ajouter)

            try:
                await page.goto(
                    url_lecteur,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_PAGE_TIMEOUT_MS,
                    referer=SITE_URL + "/",
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug(redact_text(f"goto : {e}"))

            await _cliquer_play(page)

            for _ in range(timeout * 4):
                if all_urls:
                    break
                await asyncio.sleep(0.25)

            await _executer_scans(page, mode, js_code, all_urls, _ajouter)

        await asyncio.wait_for(_corps(), timeout=_deadline_extraction(timeout))

    except asyncio.CancelledError:
        raise
    except TimeoutError:
        log.warning(redact_text(f"extraire_flux : deadline globale dépassée : {url_lecteur}"))
    except Exception as e:
        log.error(f"extraire_flux : {e}")
        _msg = str(e).lower()
        if "closed" in _msg or "crash" in _msg or "targetclosed" in type(e).__name__.lower():
            erreur_grave = True
    finally:
        await _fermer_ressources(cdp, page, ctx, _sem, _sem_acquired, erreur_grave)

    return _construire_resultat(all_urls, timeline)

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)
    url  = sys.argv[1] if len(sys.argv) > 1 else ""
    mode = sys.argv[2] if len(sys.argv) > 2 else "forensic"
    if not url:
        print("Usage : python -m engine.download.extractor.browser_extractor <url> [mode]")
        sys.exit(1)
    res = asyncio.run(extraire_flux(url, timeout=15, mode=mode))
    print(json.dumps(res, indent=2, ensure_ascii=False))
