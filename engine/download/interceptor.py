
import asyncio
import logging
import os
import re
import threading as _threading
import weakref as _weakref
from collections.abc import Callable
from urllib.parse import urlparse

from engine.config.settings import (
    BROWSER_CHANNEL,
    BROWSER_HEADLESS,
    BROWSER_PAGE_TIMEOUT_MS,
    DEFAULT_USER_AGENT,
)
from engine.download._engine_utils import est_url_http as _est_url_http
from engine.download._patterns import url_a_ignorer, url_est_stream
from engine.observability.redact import redact_text, redact_url

log = logging.getLogger("engine.download.interceptor")

_stealth_fn = None
_STEALTH_AVAILABLE = False

try:
    from playwright_stealth import Stealth as _StealthClass
    _stealth_instance = _StealthClass()

    async def _stealth_fn_v2(page):
        await _stealth_instance.apply_stealth_async(page)

    _stealth_fn = _stealth_fn_v2
    _STEALTH_AVAILABLE = True
    log.debug("playwright-stealth disponible")
except ImportError:
    log.warning("playwright-stealth introuvable. Fix → pip install playwright-stealth")

async def _appliquer_stealth(page) -> None:
    if not _STEALTH_AVAILABLE or _stealth_fn is None:
        return
    try:
        await _stealth_fn(page)
        log.debug("Stealth appliqué (navigator.webdriver masqué)")
    except Exception as e:
        log.debug(f"Stealth échoué (non bloquant) : {e}")

async def get_browser():
    return await _get_browser()

async def apply_stealth(page) -> None:
    await _appliquer_stealth(page)

PLAY_SELECTORS = (
    "video",
    ".vjs-big-play-button",
    "button.vjs-big-play-button",
    "[class*='play-btn']",
    "[class*='playButton']",
    "[aria-label*='play' i]",
    "button.play",
    ".plyr__control--overlaid",
)

USER_AGENT = DEFAULT_USER_AGENT

MAX_LECTEURS_PARALLELES = 4

MAX_CONTEXTS_SIMULTANES = 4

_ctx_semaphore_state: dict = {"sem": None, "loop": None, "mutex": _threading.Lock()}

def _loop_affine[T](
    state: dict,
    key: str,
    factory: Callable[[], T],
    describe: Callable[[asyncio.AbstractEventLoop], str],
) -> T:
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        raise
    if state[key] is not None and state["loop"] is current_loop:
        return state[key]
    with state["mutex"]:
        if state[key] is None or state["loop"] is not current_loop:
            state[key] = factory()
            state["loop"] = current_loop
            log.debug(describe(current_loop))
        return state[key]

def _ctx_semaphore() -> asyncio.Semaphore:
    return _loop_affine(
        _ctx_semaphore_state,
        "sem",
        lambda: asyncio.Semaphore(MAX_CONTEXTS_SIMULTANES),
        lambda _loop: f"ctx semaphore recréé (max={MAX_CONTEXTS_SIMULTANES})",
    )

_NOISE_EXC_NAMES = {"TargetClosedError", "CancelledError"}
_NOISE_MSG_PATTERNS = (
    "Target page, context or browser has been closed",
    "Target closed",
    "Browser has been closed",
)

_default_exception_handler = None
_handler_installed_on_loop: "_weakref.WeakSet[asyncio.AbstractEventLoop]" = _weakref.WeakSet()

def _est_bruit_attendu(context: dict) -> bool:
    exc = context.get("exception")
    if exc is not None:
        if type(exc).__name__ in _NOISE_EXC_NAMES:
            return True
        for cls in type(exc).__mro__:
            if cls.__name__ in _NOISE_EXC_NAMES:
                return True
        msg = str(exc)
        for pat in _NOISE_MSG_PATTERNS:
            if pat in msg:
                return True
    message = str(context.get("message", ""))
    for pat in _NOISE_MSG_PATTERNS:
        if pat in message:
            return True
    if "TargetClosedError" in message:
        return True
    return False

def _custom_exception_handler(loop, context: dict) -> None:
    if _est_bruit_attendu(context):
        return
    if _default_exception_handler is not None:
        try:
            _default_exception_handler(context)
        except TypeError:
            try:
                _default_exception_handler(loop, context)
            except Exception:
                log.error(redact_text(f"{context.get('message', 'unhandled')}: {context.get('exception', '?')}"))
        except Exception:
            log.error(f"{context.get('message', 'unhandled')}: {context.get('exception', '?')}")
    else:
        log.error(f"{context.get('message', 'unhandled')}: {context.get('exception', '?')}")

def _install_loop_exception_handler() -> None:
    global _default_exception_handler
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if loop in _handler_installed_on_loop:
        return
    current = loop.get_exception_handler()
    _default_exception_handler = current if current is not None else loop.default_exception_handler
    loop.set_exception_handler(_custom_exception_handler)
    _handler_installed_on_loop.add(loop)
    log.debug("loop exception handler installé")

_browser = None
_playwright = None

_browser_lock_state: dict = {"lock": None, "loop": None, "mutex": _threading.Lock()}

def _browser_lock() -> asyncio.Lock:
    return _loop_affine(
        _browser_lock_state,
        "lock",
        asyncio.Lock,
        lambda loop: f"browser asyncio.Lock recréé pour loop {id(loop)}",
    )

def _is_browser_alive(browser) -> bool:
    if browser is None:
        return False
    try:
        return bool(browser.is_connected())
    except Exception:
        return False

_LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--window-size=1920,1080",
]

async def _lancer_chromium(pw):
    """Le canal « chromium » exige le build complet de Chrome.

    C'est le meme executable que le mode visible, en « new headless » : le
    fingerprint ne bouge pas, seule la fenetre disparait. Un paquet construit
    avec ANIMESAMA_HEADLESS_ONLY ne l'embarque pas — plutot que de rester sans
    navigateur du tout, on retombe alors sur chrome-headless-shell.
    """
    try:
        return await pw.chromium.launch(
            headless=BROWSER_HEADLESS, channel=BROWSER_CHANNEL or None, args=_LAUNCH_ARGS,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if not BROWSER_CHANNEL:
            raise
        log.warning(
            "Canal « %s » indisponible (%s) — repli sur chrome-headless-shell. "
            "Le sniff continue de fonctionner, avec une empreinte navigateur plus "
            "pauvre : si un hébergeur se met à refuser, réinstalle Chromium "
            "(« playwright install chromium »).",
            BROWSER_CHANNEL, e,
        )
        return await pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)

async def _get_browser():
    global _browser, _playwright

    _install_loop_exception_handler()

    async with _browser_lock():
        if _is_browser_alive(_browser):
            return _browser

        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception:
                pass
            _playwright = None
            _browser = None

        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        try:
            _browser = await _lancer_chromium(_playwright)
        except BaseException:
            try:
                await _playwright.stop()
            except Exception:
                pass
            _playwright = None
            _browser = None
            raise
        log.debug("Browser Playwright démarré")
        return _browser

async def _reset_browser_apres_erreur() -> None:
    global _browser, _playwright
    async with _browser_lock():
        b, pw = _browser, _playwright
        _browser, _playwright = None, None
        if b is not None:
            try:
                await b.close()
            except Exception as e:
                log.debug(f"reset/close browser : {e}")
        if pw is not None:
            try:
                await pw.stop()
            except Exception as e:
                log.debug(f"reset/stop playwright : {e}")

async def fermer_browser():
    await _reset_browser_apres_erreur()
    try:
        await asyncio.sleep(0)
    except Exception:
        pass

_DECOY_MARKERS = ("preload", "blank", "/ads/", "advert")
_GRACE_MASTER_TICKS = 8
_HOTE_MORT_RE = re.compile(r"//ww\d+\.", re.I)

def _est_decoy_stream(url: str) -> bool:
    u = url.lower()
    return any(m in u for m in _DECOY_MARKERS)

def _est_url_morte(url: str) -> bool:
    return bool(_HOTE_MORT_RE.search(url or ""))

def _extract_iframe_actif() -> bool:
    return os.getenv("DL_EXTRACT_IFRAME", "").strip().lower() in ("1", "true", "yes")

async def _charger_embed(page, url_lecteur: str, site_url: str) -> None:
    if not _extract_iframe_actif():
        await page.goto(
            url_lecteur, wait_until="domcontentloaded",
            timeout=BROWSER_PAGE_TIMEOUT_MS, referer=site_url + "/",
        )
        return
    src = url_lecteur.replace('"', "%22")
    wrapper = (
        '<!DOCTYPE html><html><head>'
        '<meta name="referrer" content="strict-origin-when-cross-origin"></head>'
        '<body style="margin:0;background:#000">'
        f'<iframe src="{src}" '
        'sandbox="allow-scripts allow-same-origin allow-forms allow-presentation" '
        'allow="autoplay; encrypted-media; fullscreen" '
        'style="position:fixed;inset:0;width:100%;height:100%;border:0"></iframe>'
        '</body></html>'
    )
    await page.goto(site_url + "/", wait_until="domcontentloaded", timeout=BROWSER_PAGE_TIMEOUT_MS)
    await page.set_content(wrapper, wait_until="domcontentloaded", timeout=BROWSER_PAGE_TIMEOUT_MS)

def _meilleur_resultat(resultats: list[dict]) -> dict | None:
    if not resultats:
        return None
    m3u8 = [r for r in resultats if ".m3u8" in r.get("url", "").lower()]
    if m3u8:
        for r in m3u8:
            if not _est_decoy_stream(r.get("url", "")):
                return r
        return m3u8[0]
    for r in resultats:
        chemin = r.get("url", "").lower().split("?", 1)[0].split("#", 1)[0]
        if chemin.endswith(".txt"):
            return r
    return resultats[0]

_AD_HOSTS_RE = re.compile(
    r"(?:acscdn\.com|a-zzz\.com|googlesyndication|googletagmanager|google-analytics"
    r"|doubleclick\.net|hagne-puo|zokredirect|cloudflareinsights|popads|propellerads"
    r"|onclickads|adcash|/aclib\.js"
    r"|hilltopads|popcash|adsterra|highperformanceformat|juicyads|exoclick"
    r"|clickadu|bidgear|poptm|trafficjunky|servedby-buysellads|mgid\.com)",
    re.I,
)

async def _bloquer_pub(route) -> None:
    try:
        await route.abort()
    except Exception:
        try:
            await route.continue_()
        except Exception:
            pass

async def _nouveau_contexte(browser, site_url: str):
    ctx = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        extra_http_headers={
            "Referer": site_url + "/",
            "Origin":  site_url,
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "sec-ch-ua": '"Chromium";v="147", "Google Chrome";v="147"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
    )
    try:
        await ctx.route(_AD_HOSTS_RE, _bloquer_pub)
    except Exception:
        log.debug("ad-block route non appliquée", exc_info=True)
    return ctx

def _make_capture_handler(resultats: list[dict], urls_vues: set[str]) -> Callable[..., None]:
    def on_request(req):
        try:
            url = req.url
            if not url:
                return
            url_low = url.lower()
            if url_a_ignorer(url_low) or not url_est_stream(url_low):
                return
            if url in urls_vues:
                return
            urls_vues.add(url)
            try:
                headers = dict(req.headers)
            except Exception:
                headers = {}
            resultats.append({"url": url, "headers": headers})
            log.debug(f"URL stream capturée : {redact_url(url, 80)}")
        except Exception:
            log.debug("on_request handler error", exc_info=True)
    return on_request

async def _fermer_page_ctx(
    page, ctx, sem, acquired: bool, erreur_grave: bool, in_parallel: bool
) -> None:
    # Appelee depuis un finally, donc potentiellement pendant une annulation :
    # une CancelledError levee par un close() n'est pas rattrapee par
    # `except Exception` et emportait la liberation du semaphore avec elle.
    # Quatre annulations suffisaient a epuiser MAX_CONTEXTS_SIMULTANES et plus
    # aucune interception ne demarrait jusqu'au redemarrage.
    annulation: BaseException | None = None
    for fermable, label in ((page, "page"), (ctx, "ctx")):
        if fermable is None:
            continue
        try:
            await fermable.close()
        except asyncio.CancelledError as e:
            annulation = e
        except Exception as e:
            log.debug(f"{label}.close() : {e}")
    if acquired:
        sem.release()
    if annulation is not None:
        raise annulation
    if erreur_grave and not in_parallel:
        await _reset_browser_apres_erreur()

_INTERCEPTION_MARGIN_S = 60.0

def _deadline_interception(timeout: int) -> float:
    return BROWSER_PAGE_TIMEOUT_MS / 1000.0 + timeout + _INTERCEPTION_MARGIN_S

async def intercepter_lecteur(url_lecteur: str, timeout: int = 8, _in_parallel: bool = False) -> dict | None:
    if not url_lecteur or not _est_url_http(url_lecteur):
        log.warning(f"URL invalide ignorée : {redact_url(url_lecteur, 60)}")
        return None

    try:
        timeout = max(2, min(int(timeout or 8), 60))
    except (TypeError, ValueError):
        timeout = 8

    from engine.download._rate_limiter import hote_throttle
    _dom_lecteur = urlparse(url_lecteur).netloc.lower()
    if hote_throttle(_dom_lecteur):
        log.debug(f"lecteur throttlé (429/parking récent) — ignoré : {redact_url(url_lecteur, 60)}")
        return None

    resultats: list[dict] = []
    urls_vues:  set[str]  = set()

    ctx = None
    page = None
    erreur_grave = False
    sem = _ctx_semaphore()
    acquired = False
    try:
        async def _corps() -> None:
            nonlocal ctx, page, acquired
            if sem is not None:
                await sem.acquire()
                acquired = True
            browser = await _get_browser()
            from engine.scraping.site.animessama import SITE_URL
            ctx = await _nouveau_contexte(browser, SITE_URL)
            page = await ctx.new_page()
            await _appliquer_stealth(page)
            page.on("request", _make_capture_handler(resultats, urls_vues))

            try:
                await _charger_embed(page, url_lecteur, SITE_URL)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug(redact_text(f"chargement embed a échoué : {e}"))

            try:
                _url_courante = page.url
            except Exception:
                _url_courante = ""
            if _est_url_morte(_url_courante):
                from engine.download._rate_limiter import marquer_hote_throttle
                marquer_hote_throttle(_dom_lecteur)
                log.debug(f"lecteur mort/parking : {redact_url(_url_courante, 60)}")
                return

            await _tenter_clic_play(page)

            ticks = max(1, timeout * 4)
            premier = None
            for i in range(ticks):
                if resultats:
                    if premier is None:
                        premier = i
                    if any(
                        ".m3u8" in r.get("url", "").lower()
                        and not _est_decoy_stream(r.get("url", ""))
                        for r in resultats
                    ):
                        break
                    if i - premier >= _GRACE_MASTER_TICKS:
                        break
                await asyncio.sleep(0.25)

        await asyncio.wait_for(_corps(), timeout=_deadline_interception(timeout))

    except asyncio.CancelledError:
        raise
    except TimeoutError:
        log.warning(redact_text(f"intercepter_lecteur : deadline globale dépassée : {url_lecteur}"))
    except Exception as e:
        log.error(f"Erreur : {e}")
        erreur_grave = True
    finally:
        await _fermer_page_ctx(page, ctx, sem, acquired, erreur_grave, _in_parallel)

    return _meilleur_resultat(resultats)

async def _tenter_clic_play(page) -> None:
    try:
        from playwright.async_api import Error as PWError
    except ImportError:
        PWError = Exception  # type: ignore[assignment,misc]

    clique = False
    for frame in list(page.frames):
        for sel in PLAY_SELECTORS:
            try:
                if await frame.query_selector(sel) is None:
                    continue
                await frame.click(sel, timeout=400)
                log.debug(f"Clic play réussi ({sel}) frame={redact_url(frame.url, 40)}")
                clique = True
                break
            except asyncio.CancelledError:
                raise
            except PWError as e:
                if "closed" in str(e).lower() or "TargetClosed" in type(e).__name__:
                    return
                continue
            except Exception:
                continue
    if not clique:
        log.debug("Aucun bouton play trouvé dans les frames (autoplay attendu)")

async def _attendre_premier_flux(
    tasks: list[asyncio.Task], on_win: Callable[[str], None] | None
) -> tuple[dict | None, list[str]]:
    result = None
    erreurs: list[str] = []
    try:
        for coro in asyncio.as_completed(tasks):
            try:
                src, r = await coro
                if r:
                    result = r
                    if on_win is not None:
                        try:
                            on_win(src)
                        except Exception:
                            log.debug("on_win callback error", exc_info=True)
                    break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                erreurs.append(str(e)[:120])
                log.debug(f"Lecteur en erreur : {e}")
                continue
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
    return result, erreurs

async def intercepter_lecteurs_parallele(
    lecteurs: list[dict],
    timeout:  int = 8,
    on_win:   Callable[[str], None] | None = None,
) -> dict | None:
    if not lecteurs:
        return None
    lecteurs_ok = [l for l in lecteurs if isinstance(l, dict) and l.get("src")]
    if not lecteurs_ok:
        log.warning("Aucun lecteur exploitable dans la liste")
        return None

    if len(lecteurs_ok) > MAX_LECTEURS_PARALLELES:
        log.debug(
            f"{len(lecteurs_ok)} lecteurs — limite à "
            f"{MAX_LECTEURS_PARALLELES} en parallèle"
        )
        lecteurs_ok = lecteurs_ok[:MAX_LECTEURS_PARALLELES]

    _install_loop_exception_handler()

    async def _run(src: str) -> tuple[str, dict | None]:
        return src, await intercepter_lecteur(src, timeout, _in_parallel=True)

    tasks = [asyncio.create_task(_run(lec["src"])) for lec in lecteurs_ok]

    result, erreurs = await _attendre_premier_flux(tasks, on_win)

    if result is None and erreurs:
        log.warning(f"tous les lecteurs ont échoué : {erreurs[:3]}")

    if result is None and not _is_browser_alive(_browser):
        await _reset_browser_apres_erreur()

    return result
