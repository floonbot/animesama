
import asyncio
import logging
import threading

import requests as req

from engine.auth.storage import AuthStorage

log = logging.getLogger("engine.auth")

from engine.scraping.site.animessama import GETDATA_API, LOGIN_API, LOGIN_URL, SITE_DOMAIN

_KEEPALIVE_INTERVAL = 15 * 60

from engine.config.settings import DEFAULT_USER_AGENT as USER_AGENT


def _purger_caches_du_compte() -> None:
    """Les trois caches qui appartiennent au compte, et eux seuls.

    Favoris et nouveautes sont derives de l'identite : les laisser au chaud
    servait la liste du compte precedent pendant 300 s apres un changement.
    La librairie n'en fait pas partie — les fichiers locaux ne bougent pas
    quand on se connecte. Voir tests/test_matrice_invalidations.py.
    """
    for module, fonction in (
        ("engine.scraping.scraper", "clear_session_cache"),
        ("engine.library.updates", "invalider_cache_updates"),
    ):
        try:
            import importlib
            getattr(importlib.import_module(module), fonction)()
        except Exception:
            log.debug("%s.%s failed", module, fonction, exc_info=True)
    try:
        from engine.scraping._cache import cache
        cache.invalidate_fav()
    except Exception:
        log.debug("invalidate_fav failed", exc_info=True)

class AuthManager:

    def __init__(self):
        self.storage    = AuthStorage()
        self.cookies:   list = []
        self.username:  str | None = None
        self._logged_in = False
        self._login_lock_holder: dict = {"lock": None}
        self._keepalive_thread: threading.Thread | None = None
        self._keepalive_stop   = threading.Event()
        self._keepalive_gen    = 0

    def _login_lock(self) -> asyncio.Lock:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            raise
        state = self._login_lock_holder
        if state.get("lock") is not None and state.get("loop") is current_loop:
            return state["lock"]
        mutex = state.setdefault("mutex", threading.Lock())
        with mutex:
            if state.get("lock") is None or state.get("loop") is not current_loop:
                state["lock"] = asyncio.Lock()
                state["loop"] = current_loop
                log.debug(f"re_login asyncio.Lock recréé pour loop {id(current_loop)}")
            return state["lock"]

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    def keepalive_session(self) -> bool:
        if not self._logged_in or not self.cookies:
            return False
        s = req.Session()
        try:
            s.headers["User-Agent"] = USER_AGENT
            for c in self.cookies:
                if isinstance(c, dict) and c.get("name"):
                    s.cookies.set(
                        c["name"], c.get("value", ""),
                        domain=c.get("domain", ""),
                        path=c.get("path", "/"),
                    )
            r = s.get(GETDATA_API, timeout=10, allow_redirects=True)
            if r.ok:
                try:
                    data = r.json()
                except (ValueError, req.exceptions.RequestException):
                    data = None
                if isinstance(data, dict) and data.get("logged_in"):
                    log.debug("Keepalive OK")
                    return True
            log.warning("Keepalive : session expirée — re-login différé à la prochaine action")
            return False
        except Exception as e:
            log.debug(f"keepalive_session : {e}")
            return False
        finally:
            try:
                s.close()
            except Exception:
                pass

    def start_keepalive_loop(self) -> None:
        if (
            self._keepalive_thread
            and self._keepalive_thread.is_alive()
            and not self._keepalive_stop.is_set()
        ):
            return
        self._keepalive_stop.clear()
        self._keepalive_gen += 1
        my_gen     = self._keepalive_gen
        stop_event = self._keepalive_stop

        def _loop():
            echecs = 0
            while True:
                interval = min(_KEEPALIVE_INTERVAL * (2 ** echecs), 7200)
                if stop_event.wait(interval):
                    break
                if self._keepalive_gen != my_gen:
                    break
                if not self._logged_in:
                    continue
                ok = self.keepalive_session()
                if ok:
                    echecs = 0
                else:
                    echecs += 1
                    prochaine = min(_KEEPALIVE_INTERVAL * (2 ** echecs), 7200) // 60
                    log.debug(f"Keepalive echec ({echecs}x) — prochain essai dans {prochaine}min")

        self._keepalive_thread = threading.Thread(
            target=_loop, daemon=True, name="auth_keepalive"
        )
        self._keepalive_thread.start()
        log.debug(f"Keepalive démarré (intervalle de base {_KEEPALIVE_INTERVAL//60}min, backoff x2 sur echec)")

    def stop_keepalive_loop(self) -> None:
        self._keepalive_stop.set()

    @staticmethod
    def _cookies_depuis_session(s: req.Session) -> list:
        cookies = []
        for c in s.cookies:
            cookies.append({
                "name":     c.name,
                "value":    c.value,
                "domain":   c.domain or ("." + SITE_DOMAIN),
                "path":     c.path or "/",
                "secure":   bool(c.secure),
                "httpOnly": False,
                "sameSite": "Lax",
                "expires":  c.expires if c.expires else -1,
            })
        return cookies

    @staticmethod
    def _message_erreur_login(r: req.Response) -> str:
        try:
            data = r.json()
        except (ValueError, req.exceptions.RequestException):
            data = None
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])[:200]
        return "Identifiants incorrects"

    def _login_requests(self, pseudo: str, password: str) -> dict:
        try:
            s = req.Session()
            s.headers["User-Agent"] = USER_AGENT

            r = s.post(
                LOGIN_API,
                json={"pseudo": pseudo, "password": password},
                headers={"Referer": LOGIN_URL, "X-Requested-With": "XMLHttpRequest"},
                timeout=15,
                allow_redirects=True,
            )

            if r.status_code == 429:
                return {"ok": False, "message": "Trop de tentatives, réessaie dans un moment", "rejected": True}

            if r.ok:
                cookies = self._cookies_depuis_session(s)
                if not any(c["name"] == "remember_token" for c in cookies):
                    log.warning("Login accepté mais 'remember_token' absent — session peut-être incomplète")
                return {"ok": True, "cookies": cookies}

            return {
                "ok": False,
                "message": self._message_erreur_login(r),
                "rejected": r.status_code in (400, 401, 403, 422),
            }

        except Exception as e:
            log.debug(f"_login_requests : {e}")
            return {"ok": False, "message": str(e)[:100], "rejected": False}

    async def _login_playwright(self, pseudo: str, password: str) -> dict:
        from playwright.async_api import TimeoutError as PWTimeout
        from playwright.async_api import async_playwright
        browser = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                ctx     = await browser.new_context(user_agent=USER_AGENT)
                page    = await ctx.new_page()

                await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)

                await page.wait_for_selector("#loginPseudo", timeout=5_000)
                await page.fill("#loginPseudo", pseudo)
                await page.fill("#loginPassword", password)

                await page.click("#formLogin button[type='submit']")
                try:
                    await page.wait_for_url("**/profil**", timeout=15_000)
                except PWTimeout:
                    pass

                cookies = await ctx.cookies()
                if any(c.get("name") == "remember_token" for c in cookies):
                    return {"ok": True, "cookies": cookies}
                return {"ok": False, "message": "Identifiants incorrects"}

        except Exception as e:
            log.error(f"_login_playwright : {e}")
            return {"ok": False, "message": "Erreur de connexion — vérifie tes identifiants"}
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def login_async(self, pseudo: str, password: str) -> dict:
        pseudo   = (pseudo or "").strip()
        password = password or ""
        if not pseudo or not password:
            return {"ok": False, "message": "Pseudo et mot de passe requis"}

        log.info(f"Connexion pour {pseudo}...")

        result = await asyncio.to_thread(self._login_requests, pseudo, password)

        if not result.get("ok") and not result.get("rejected"):
            log.debug(f"Login requests échoué ({result.get('message')}) → Playwright")
            result = await self._login_playwright(pseudo, password)

        if not result.get("ok"):
            return {"ok": False, "message": result.get("message", "Erreur de connexion")}

        self.cookies    = result["cookies"]
        self.username   = pseudo
        self._logged_in = True

        _purger_caches_du_compte()

        try:
            self.storage.save_credentials(pseudo, password)
            self.storage.save_cookies(self.cookies, self.username)
        except Exception as save_err:
            log.warning(f"Sauvegarde session impossible : {save_err}")

        log.success(f"Connecté en tant que {self.username}")  # type: ignore[attr-defined]
        log.debug(f"{len(self.cookies)} cookies récupérés")
        self.start_keepalive_loop()

        return {"ok": True, "message": "Connecté !", "username": self.username}

    def restore_session(self) -> bool:
        try:
            session = self.storage.load_session()
        except Exception as e:
            log.warning(f"restore_session : {e}")
            return False
        if not session or not session.get("cookies"):
            return False
        cookies = session.get("cookies")
        if not isinstance(cookies, list):
            log.warning("format cookies invalide")
            return False
        self.cookies    = cookies
        self.username   = session.get("username") or None
        self._logged_in = True
        log.debug(f"Session chargée — {self.username or '?'} ({len(self.cookies)} cookies)")
        self.start_keepalive_loop()
        return True

    async def re_login_if_needed(self) -> bool:
        async with self._login_lock():
            try:
                creds = self.storage.load_credentials()
            except Exception as e:
                log.warning(f"load_credentials : {e}")
                return False
            if not creds:
                log.warning("Pas de credentials sauvegardés — connexion manuelle requise")
                return False
            log.info("Re-login automatique...")
            try:
                result = await self.login_async(creds["email"], creds["password"])
            except Exception as e:
                log.error(f"re_login_if_needed : {e}")
                return False
            return bool(result and result.get("ok"))

    def logout(self) -> None:
        self.stop_keepalive_loop()
        self.cookies    = []
        self.username   = None
        self._logged_in = False
        _purger_caches_du_compte()
        try:
            self.storage.clear_all()
        except Exception as e:
            log.warning(f"logout/clear_all : {e}")
        log.info("Déconnecté")

auth_manager = AuthManager()
