import asyncio

import pytest

import engine.auth.manager as mgr_mod
import engine.config.logging_setup  # noqa: F401
import engine.scraping.scraper as scraper_mod
from engine.auth.manager import AuthManager
from engine.scraping.site.animessama import LOGIN_API


class FakeStorage:
    def __init__(self):
        self.saved_credentials = []
        self.saved_cookies = []
        self.credentials_exc = None
        self.cookies_exc = None

    def save_credentials(self, pseudo, password):
        if self.credentials_exc is not None:
            raise self.credentials_exc
        self.saved_credentials.append((pseudo, password))

    def save_cookies(self, cookies, username=""):
        if self.cookies_exc is not None:
            raise self.cookies_exc
        self.saved_cookies.append((cookies, username))


class FakeCookie:
    def __init__(self, name, value, domain="", path="", secure=False, expires=None):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.secure = secure
        self.expires = expires


class FakeResponse:
    def __init__(self, ok=True, status_code=200, json_data=None, json_exc=None):
        self.ok = ok
        self.status_code = status_code
        self._json_data = json_data
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


class FakeReqSession:
    last_instance = None

    def __init__(self, post_response=None, cookies=(), post_exc=None):
        self.headers = {}
        self.cookies = list(cookies)
        self._post_response = post_response
        self._post_exc = post_exc
        self.post_calls = []
        FakeReqSession.last_instance = self

    def post(self, url, json=None, headers=None, timeout=None, allow_redirects=None):
        self.post_calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        if self._post_exc is not None:
            raise self._post_exc
        return self._post_response


@pytest.fixture(autouse=True)
def _reset_module_globals():
    saved_session_cls = mgr_mod.req.Session
    saved_clear_cache = scraper_mod.clear_session_cache
    FakeReqSession.last_instance = None
    yield
    mgr_mod.req.Session = saved_session_cls
    scraper_mod.clear_session_cache = saved_clear_cache
    FakeReqSession.last_instance = None


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setattr(mgr_mod, "AuthStorage", FakeStorage)
    return AuthManager()


def _install_session(monkeypatch, session):
    monkeypatch.setattr(mgr_mod.req, "Session", lambda: session)


def test_login_requests_success_posts_json_and_builds_cookies(mgr, monkeypatch):
    cookie = FakeCookie(
        "remember_token", "323966:hash", domain="example.test", path="/app",
        secure=True, expires=1234567890,
    )
    session = FakeReqSession(
        post_response=FakeResponse(ok=True, status_code=200), cookies=[cookie]
    )
    _install_session(monkeypatch, session)

    result = mgr._login_requests("utilisateur_test", "pw")

    assert result["ok"] is True
    assert result["cookies"] == [{
        "name": "remember_token",
        "value": "323966:hash",
        "domain": "example.test",
        "path": "/app",
        "secure": True,
        "httpOnly": False,
        "sameSite": "Lax",
        "expires": 1234567890,
    }]
    assert session.headers["User-Agent"] == mgr_mod.USER_AGENT
    call = session.post_calls[0]
    assert call["url"] == LOGIN_API
    assert call["json"] == {"pseudo": "utilisateur_test", "password": "pw"}
    assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_login_requests_success_without_remember_token_still_ok(mgr, monkeypatch):
    cookie = FakeCookie("PHPSESSID", "abc", domain="", path="", secure=True, expires=None)
    session = FakeReqSession(
        post_response=FakeResponse(ok=True, status_code=200), cookies=[cookie]
    )
    _install_session(monkeypatch, session)

    result = mgr._login_requests("utilisateur_test", "pw")

    assert result["ok"] is True
    assert result["cookies"][0]["name"] == "PHPSESSID"
    assert result["cookies"][0]["domain"] == ".anime-sama.to"
    assert result["cookies"][0]["expires"] == -1


def test_login_requests_failure_401_parses_error(mgr, monkeypatch):
    session = FakeReqSession(
        post_response=FakeResponse(
            ok=False, status_code=401,
            json_data={"error": "Pseudo ou mot de passe incorrect"},
        )
    )
    _install_session(monkeypatch, session)

    result = mgr._login_requests("utilisateur_test", "bad")

    assert result == {
        "ok": False,
        "message": "Pseudo ou mot de passe incorrect",
        "rejected": True,
    }


def test_login_requests_failure_default_message_non_rejected(mgr, monkeypatch):
    session = FakeReqSession(
        post_response=FakeResponse(ok=False, status_code=500, json_data={"nope": 1})
    )
    _install_session(monkeypatch, session)

    result = mgr._login_requests("utilisateur_test", "pw")

    assert result == {"ok": False, "message": "Identifiants incorrects", "rejected": False}


def test_login_requests_failure_json_exception_falls_back(mgr, monkeypatch):
    session = FakeReqSession(
        post_response=FakeResponse(ok=False, status_code=403, json_exc=ValueError("no json"))
    )
    _install_session(monkeypatch, session)

    result = mgr._login_requests("utilisateur_test", "pw")

    assert result == {"ok": False, "message": "Identifiants incorrects", "rejected": True}


def test_login_requests_rate_limited_is_rejected(mgr, monkeypatch):
    session = FakeReqSession(post_response=FakeResponse(ok=False, status_code=429))
    _install_session(monkeypatch, session)

    result = mgr._login_requests("utilisateur_test", "pw")

    assert result["ok"] is False
    assert result["rejected"] is True
    assert "tentatives" in result["message"].lower()


def test_login_requests_exception_truncates_and_not_rejected(mgr, monkeypatch):
    session = FakeReqSession(post_exc=RuntimeError("E" * 250))
    _install_session(monkeypatch, session)

    result = mgr._login_requests("utilisateur_test", "pw")

    assert result["ok"] is False
    assert result["message"] == ("E" * 250)[:100]
    assert len(result["message"]) == 100
    assert result["rejected"] is False


def test_login_async_success_calls_side_effects(mgr, monkeypatch):
    cookies = [{"name": "remember_token", "value": "323966:h"}]
    mgr._login_requests = lambda pseudo, password: {"ok": True, "cookies": cookies}

    cache_calls = []
    monkeypatch.setattr(
        scraper_mod, "clear_session_cache", lambda: cache_calls.append(1)
    )
    keepalive_calls = []
    monkeypatch.setattr(mgr, "start_keepalive_loop", lambda: keepalive_calls.append(1))

    result = asyncio.run(mgr.login_async("utilisateur_test", "pw"))

    assert result == {"ok": True, "message": "Connecté !", "username": "utilisateur_test"}
    assert mgr._logged_in is True
    assert mgr.cookies == cookies
    assert mgr.username == "utilisateur_test"
    assert cache_calls == [1]
    assert keepalive_calls == [1]
    assert mgr.storage.saved_credentials == [("utilisateur_test", "pw")]
    assert mgr.storage.saved_cookies == [(cookies, "utilisateur_test")]


def test_login_async_rejected_skips_playwright(mgr, monkeypatch):
    mgr._login_requests = lambda pseudo, password: {
        "ok": False, "message": "Pseudo ou mot de passe incorrect", "rejected": True,
    }
    pw_calls = []

    async def _pw(pseudo, password):
        pw_calls.append(1)
        return {"ok": True, "cookies": []}

    monkeypatch.setattr(mgr, "_login_playwright", _pw)

    result = asyncio.run(mgr.login_async("utilisateur_test", "bad"))

    assert result == {"ok": False, "message": "Pseudo ou mot de passe incorrect"}
    assert pw_calls == []
    assert mgr._logged_in is False


def test_login_async_transport_error_falls_back_to_playwright(mgr, monkeypatch):
    cookies = [{"name": "remember_token", "value": "323966:h"}]
    mgr._login_requests = lambda pseudo, password: {
        "ok": False, "message": "network down", "rejected": False,
    }

    async def _pw(pseudo, password):
        return {"ok": True, "cookies": cookies}

    monkeypatch.setattr(mgr, "_login_playwright", _pw)
    monkeypatch.setattr(scraper_mod, "clear_session_cache", lambda: None)
    monkeypatch.setattr(mgr, "start_keepalive_loop", lambda: None)

    result = asyncio.run(mgr.login_async("utilisateur_test", "pw"))

    assert result["ok"] is True
    assert mgr.cookies == cookies
    assert mgr.username == "utilisateur_test"


def test_login_async_save_credentials_raises_still_ok(mgr, monkeypatch):
    cookies = [{"name": "remember_token", "value": "1"}]
    mgr._login_requests = lambda pseudo, password: {"ok": True, "cookies": cookies}
    monkeypatch.setattr(scraper_mod, "clear_session_cache", lambda: None)
    keepalive_calls = []
    monkeypatch.setattr(mgr, "start_keepalive_loop", lambda: keepalive_calls.append(1))
    mgr.storage.credentials_exc = OSError("disk full")

    result = asyncio.run(mgr.login_async("utilisateur_test", "pw"))

    assert result["ok"] is True
    assert mgr._logged_in is True
    assert mgr.storage.saved_credentials == []
    assert mgr.storage.saved_cookies == []
    assert keepalive_calls == [1]


def test_login_async_save_cookies_raises_still_ok(mgr, monkeypatch):
    cookies = [{"name": "remember_token", "value": "1"}]
    mgr._login_requests = lambda pseudo, password: {"ok": True, "cookies": cookies}
    monkeypatch.setattr(scraper_mod, "clear_session_cache", lambda: None)
    monkeypatch.setattr(mgr, "start_keepalive_loop", lambda: None)
    mgr.storage.cookies_exc = OSError("disk full")

    result = asyncio.run(mgr.login_async("utilisateur_test", "pw"))

    assert result["ok"] is True
    assert mgr.storage.saved_credentials == [("utilisateur_test", "pw")]
    assert mgr.storage.saved_cookies == []


def test_login_async_empty_inputs_rejected(mgr):
    assert asyncio.run(mgr.login_async("", "pw")) == {
        "ok": False, "message": "Pseudo et mot de passe requis",
    }
    assert asyncio.run(mgr.login_async("utilisateur_test", "")) == {
        "ok": False, "message": "Pseudo et mot de passe requis",
    }
