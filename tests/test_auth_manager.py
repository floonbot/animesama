import asyncio

import pytest

import engine.auth.manager as mgr_mod
import engine.config.logging_setup  # noqa: F401
import engine.scraping.scraper as scraper_mod
from engine.auth.manager import AuthManager


class FakeStorage:
    def __init__(self):
        self.session = None
        self.credentials = None
        self.saved_credentials = []
        self.saved_cookies = []
        self.clear_all_calls = 0

    def load_session(self):
        return self.session

    def load_credentials(self):
        return self.credentials

    def save_credentials(self, email, password):
        self.saved_credentials.append((email, password))

    def save_cookies(self, cookies, username=""):
        self.saved_cookies.append((cookies, username))

    def clear_all(self):
        self.clear_all_calls += 1


class FakeResponse:
    def __init__(self, ok=True, text="", status_code=200, json_data=None, json_exc=None):
        self.ok = ok
        self.text = text
        self.status_code = status_code
        self._json_data = json_data
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


class FakeReqSession:
    last_instance = None

    def __init__(self, response=None, raise_on_get=None):
        self.headers = {}
        self.cookies = FakeCookieJar()
        self._response = response
        self._raise_on_get = raise_on_get
        self.get_calls = []
        self.closed = False
        FakeReqSession.last_instance = self

    def get(self, url, timeout=None, allow_redirects=None):
        self.get_calls.append(url)
        if self._raise_on_get is not None:
            raise self._raise_on_get
        return self._response

    def close(self):
        self.closed = True


class FakeCookieJar:
    def __init__(self):
        self.set_calls = []

    def set(self, name, value, domain="", path="/"):
        self.set_calls.append((name, value, domain, path))


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
    monkeypatch.setattr(scraper_mod, "clear_session_cache", lambda: None)
    instance = AuthManager()
    monkeypatch.setattr(instance, "start_keepalive_loop", lambda: None)
    return instance


def test_re_login_no_credentials(mgr):
    mgr.storage.credentials = None
    attempts = []
    mgr.login_async = lambda *a, **k: attempts.append(a)
    result = asyncio.run(mgr.re_login_if_needed())
    assert result is False
    assert attempts == []


def test_re_login_success(mgr):
    mgr.storage.credentials = {"email": "u@x.com", "password": "pw"}
    seen = {}

    async def fake_login(email, password):
        seen["email"] = email
        seen["password"] = password
        return {"ok": True}

    mgr.login_async = fake_login
    result = asyncio.run(mgr.re_login_if_needed())
    assert result is True
    assert seen == {"email": "u@x.com", "password": "pw"}


def test_re_login_login_raises(mgr):
    mgr.storage.credentials = {"email": "u@x.com", "password": "pw"}

    async def fake_login(email, password):
        raise RuntimeError("boom")

    mgr.login_async = fake_login
    result = asyncio.run(mgr.re_login_if_needed())
    assert result is False


def test_restore_session_none(mgr):
    mgr.storage.session = None
    assert mgr.restore_session() is False
    assert mgr._logged_in is False


def test_restore_session_valid(mgr):
    cookies = [{"name": "sess", "value": "1"}]
    mgr.storage.session = {"cookies": cookies, "username": "u"}
    assert mgr.restore_session() is True
    assert mgr._logged_in is True
    assert mgr.cookies == cookies
    assert mgr.username == "u"


def test_restore_session_cookies_not_list(mgr):
    mgr.storage.session = {"cookies": "notalist", "username": "u"}
    assert mgr.restore_session() is False
    assert mgr._logged_in is False


def test_login_async_empty(mgr):
    result = asyncio.run(mgr.login_async("", ""))
    assert result["ok"] is False
    assert mgr._logged_in is False


def test_login_async_requests_success(mgr):
    cookies = [{"name": "sess", "value": "1"}]
    mgr._login_requests = lambda email, password: {"ok": True, "cookies": cookies}
    result = asyncio.run(mgr.login_async("utilisateur_test", "pw"))
    assert result["ok"] is True
    assert mgr._logged_in is True
    assert mgr.cookies == cookies
    assert mgr.username == "utilisateur_test"
    assert mgr.storage.saved_credentials == [("utilisateur_test", "pw")]
    assert mgr.storage.saved_cookies == [(cookies, "utilisateur_test")]


def test_login_async_playwright_fallback(mgr):
    pw_cookies = [{"name": "pw", "value": "2"}]
    mgr._login_requests = lambda email, password: {"ok": False, "message": "nope"}

    async def fake_pw(email, password):
        return {"ok": True, "cookies": pw_cookies}

    mgr._login_playwright = fake_pw
    result = asyncio.run(mgr.login_async("user@x.com", "pw"))
    assert result["ok"] is True
    assert mgr._logged_in is True
    assert mgr.cookies == pw_cookies


def test_login_async_both_fail(mgr):
    mgr._login_requests = lambda email, password: {"ok": False, "message": "nope"}

    async def fake_pw(email, password):
        return {"ok": False, "message": "still nope"}

    mgr._login_playwright = fake_pw
    result = asyncio.run(mgr.login_async("user@x.com", "pw"))
    assert result["ok"] is False
    assert mgr._logged_in is False


def test_keepalive_not_logged_in(mgr):
    mgr._logged_in = False
    mgr.cookies = []
    assert mgr.keepalive_session() is False


def test_keepalive_logged_in_ok(mgr, monkeypatch):
    mgr._logged_in = True
    mgr.cookies = [{"name": "sess", "value": "1", "domain": "x", "path": "/"}]
    resp = FakeResponse(ok=True, json_data={"logged_in": True})
    monkeypatch.setattr(
        mgr_mod.req, "Session", lambda: FakeReqSession(response=resp)
    )
    assert mgr.keepalive_session() is True
    assert FakeReqSession.last_instance.closed is True
    assert FakeReqSession.last_instance.cookies.set_calls == [
        ("sess", "1", "x", "/")
    ]


def test_keepalive_logged_in_no_marker(mgr, monkeypatch):
    mgr._logged_in = True
    mgr.cookies = [{"name": "sess", "value": "1"}]
    resp = FakeResponse(ok=True, text="logged out page")
    monkeypatch.setattr(
        mgr_mod.req, "Session", lambda: FakeReqSession(response=resp)
    )
    assert mgr.keepalive_session() is False


def test_keepalive_http_error_with_marker_is_false(mgr, monkeypatch):
    """An error response (ok=False) is rejected even if the body carries the logged-in marker."""
    mgr._logged_in = True
    mgr.cookies = [{"name": "sess", "value": "1"}]
    resp = FakeResponse(ok=False, text="error page window.ASN_USER_ID = 1")
    monkeypatch.setattr(
        mgr_mod.req, "Session", lambda: FakeReqSession(response=resp)
    )
    assert mgr.keepalive_session() is False


def test_logout(mgr):
    mgr._logged_in = True
    mgr.cookies = [{"name": "sess", "value": "1"}]
    mgr.username = "user"
    mgr.logout()
    assert mgr._logged_in is False
    assert mgr.cookies == []
    assert mgr.username is None
    assert mgr.storage.clear_all_calls == 1
