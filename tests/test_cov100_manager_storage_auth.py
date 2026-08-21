import asyncio
import os

import pytest

import engine.auth.manager as mgr_mod
import engine.auth.storage as storage_mod
import engine.config.logging_setup  # noqa: F401
import engine.scraping.scraper as scraper_mod
from engine.auth.manager import AuthManager


class FakeStorage:
    def __init__(self):
        self.session = None
        self.credentials = None
        self.load_session_exc = None
        self.load_credentials_exc = None
        self.clear_all_exc = None
        self.clear_all_calls = 0

    def load_session(self):
        if self.load_session_exc is not None:
            raise self.load_session_exc
        return self.session

    def load_credentials(self):
        if self.load_credentials_exc is not None:
            raise self.load_credentials_exc
        return self.credentials

    def save_credentials(self, email, password):
        pass

    def save_cookies(self, cookies, username=""):
        pass

    def clear_all(self):
        self.clear_all_calls += 1
        if self.clear_all_exc is not None:
            raise self.clear_all_exc


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


@pytest.fixture(autouse=True)
def _reset_module_globals():
    saved_session_cls = mgr_mod.req.Session
    saved_clear_cache = scraper_mod.clear_session_cache
    yield
    mgr_mod.req.Session = saved_session_cls
    scraper_mod.clear_session_cache = saved_clear_cache


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setattr(mgr_mod, "AuthStorage", FakeStorage)
    instance = AuthManager()
    monkeypatch.setattr(instance, "start_keepalive_loop", lambda: None)
    return instance


def test_login_lock_outside_running_loop_reraises(mgr):
    with pytest.raises(RuntimeError):
        mgr._login_lock()


def test_keepalive_get_raises_returns_false(mgr, monkeypatch):
    mgr._logged_in = True
    mgr.cookies = [{"name": "sess", "value": "1"}]

    class RaisingSession:
        def __init__(self):
            self.headers = {}

            class _Jar:
                def set(self, *a, **k):
                    pass

            self.cookies = _Jar()
            self.closed = False

        def get(self, *a, **k):
            raise RuntimeError("network boom")

        def close(self):
            self.closed = True

    sess = RaisingSession()
    monkeypatch.setattr(mgr_mod.req, "Session", lambda: sess)
    assert mgr.keepalive_session() is False
    assert sess.closed is True


def test_keepalive_close_raises_is_swallowed(mgr, monkeypatch):
    mgr._logged_in = True
    mgr.cookies = [{"name": "sess", "value": "1"}]
    resp = FakeResponse(ok=True, json_data={"logged_in": True})

    class CloseRaisesSession:
        def __init__(self):
            self.headers = {}

            class _Jar:
                def set(self, *a, **k):
                    pass

            self.cookies = _Jar()

        def get(self, *a, **k):
            return resp

        def close(self):
            raise RuntimeError("close boom")

    monkeypatch.setattr(mgr_mod.req, "Session", lambda: CloseRaisesSession())
    assert mgr.keepalive_session() is True


def test_login_requests_error_message_parse_exception_falls_back(mgr, monkeypatch):
    post_resp = FakeResponse(ok=False, status_code=500, json_exc=ValueError("not json"))

    class FakeReqSession:
        def __init__(self):
            self.headers = {}

            class _Jar(list):
                pass

            self.cookies = _Jar()

        def post(self, *a, **k):
            return post_resp

    monkeypatch.setattr(mgr_mod.req, "Session", lambda: FakeReqSession())

    result = mgr._login_requests("utilisateur_test", "pw")
    assert result == {"ok": False, "message": "Identifiants incorrects", "rejected": False}


def test_login_async_clear_session_cache_failure_still_ok(mgr, monkeypatch):
    cookies = [{"name": "sess", "value": "1"}]
    mgr._login_requests = lambda email, password: {"ok": True, "cookies": cookies}

    def _boom():
        raise RuntimeError("cache boom")

    monkeypatch.setattr(scraper_mod, "clear_session_cache", _boom)

    result = asyncio.run(mgr.login_async("user@x.com", "pw"))
    assert result["ok"] is True
    assert mgr._logged_in is True


def test_restore_session_load_session_raises_returns_false(mgr):
    mgr.storage.load_session_exc = RuntimeError("disk fail")
    assert mgr.restore_session() is False
    assert mgr._logged_in is False


def test_re_login_load_credentials_raises_returns_false(mgr):
    mgr.storage.load_credentials_exc = RuntimeError("keyring fail")
    called = []
    mgr.login_async = lambda *a, **k: called.append(a)
    result = asyncio.run(mgr.re_login_if_needed())
    assert result is False
    assert called == []


def test_logout_clear_session_cache_failure_swallowed(mgr, monkeypatch):
    mgr._logged_in = True
    mgr.cookies = [{"name": "x"}]
    mgr.username = "u"

    def _boom():
        raise RuntimeError("cache boom")

    monkeypatch.setattr(scraper_mod, "clear_session_cache", _boom)
    mgr.logout()
    assert mgr._logged_in is False
    assert mgr.storage.clear_all_calls == 1


def test_logout_clear_all_failure_swallowed(mgr, monkeypatch):
    mgr._logged_in = True
    mgr.cookies = [{"name": "x"}]
    mgr.username = "u"
    monkeypatch.setattr(scraper_mod, "clear_session_cache", lambda: None)
    mgr.storage.clear_all_exc = RuntimeError("keyring delete fail")
    mgr.logout()
    assert mgr._logged_in is False
    assert mgr.cookies == []
    assert mgr.username is None
    assert mgr.storage.clear_all_calls == 1


@pytest.fixture
def _storage_isolate(tmp_path, monkeypatch):
    kr: dict[str, str] = {}

    monkeypatch.setattr(storage_mod, "_kr_get", lambda u: kr.get(u))
    monkeypatch.setattr(storage_mod, "_kr_set", lambda u, v: kr.__setitem__(u, v))
    monkeypatch.setattr(storage_mod, "_kr_delete", lambda u: kr.pop(u, None))
    monkeypatch.setattr(storage_mod, "COOKIES_FILE", tmp_path / "cookies.enc")
    return kr


def test_encrypt_raises_logs_and_reraises(_storage_isolate, monkeypatch):
    def _boom(*, allow_create=True):
        raise RuntimeError("no fernet")

    monkeypatch.setattr(storage_mod, "_get_fernet", _boom)
    with pytest.raises(RuntimeError):
        storage_mod._encrypt("secret")


def test_save_cookies_replace_fails_cleans_up_tmp(_storage_isolate, monkeypatch):
    st = storage_mod.AuthStorage()

    def _replace_boom(src, dst):
        raise OSError("replace refused")

    monkeypatch.setattr(os, "replace", _replace_boom)

    st.save_cookies([{"name": "x"}], "u")

    assert not storage_mod.COOKIES_FILE.exists()
    assert not storage_mod.COOKIES_FILE.with_suffix(".enc.tmp").exists()


def test_save_cookies_replace_fails_and_tmp_unlink_raises(monkeypatch, tmp_path):
    kr: dict[str, str] = {}
    monkeypatch.setattr(storage_mod, "_kr_get", lambda u: kr.get(u))
    monkeypatch.setattr(storage_mod, "_kr_set", lambda u, v: kr.__setitem__(u, v))

    class FakeTmp:
        def write_text(self, data, encoding=None):
            pass

        def exists(self):
            return True

        def unlink(self):
            raise OSError("unlink refused")

    class FakeCookiesFile:
        def with_suffix(self, suffix):
            return FakeTmp()

    monkeypatch.setattr(storage_mod, "COOKIES_FILE", FakeCookiesFile())

    def _replace_boom(src, dst):
        raise OSError("replace refused")

    monkeypatch.setattr(os, "replace", _replace_boom)

    st = storage_mod.AuthStorage()
    st.save_cookies([{"name": "x"}], "u")


def test_load_session_stat_oserror_continues_then_decrypts(_storage_isolate, monkeypatch):
    st = storage_mod.AuthStorage()
    token = storage_mod._encrypt(
        '{"cookies": [{"name": "sid"}], "username": "u"}'
    )
    storage_mod.COOKIES_FILE.write_text(token, encoding="utf-8")

    # On enveloppe le chemin au lieu de compter les appels a os.stat : depuis
    # 3.14, Path.exists() passe par nt._path_exists et n'appelle plus os.stat,
    # donc un compteur ne declenchait plus jamais la branche visee.
    class _StatRefuse:
        def __init__(self, reel):
            self._reel = reel
            self.appels = 0

        def __getattr__(self, nom):
            return getattr(self._reel, nom)

        def stat(self, *a, **k):
            self.appels += 1
            raise OSError("stat refused")

    cf = _StatRefuse(storage_mod.COOKIES_FILE)
    monkeypatch.setattr(storage_mod, "COOKIES_FILE", cf)

    out = st.load_session()
    assert out == {"cookies": [{"name": "sid"}], "username": "u"}
    assert cf.appels == 1


def test_clear_unlink_raises_is_logged(monkeypatch, tmp_path):
    class FakeCookiesFile:
        def exists(self):
            return True

        def unlink(self):
            raise OSError("unlink refused")

    monkeypatch.setattr(storage_mod, "COOKIES_FILE", FakeCookiesFile())
    st = storage_mod.AuthStorage()
    st.clear()


WRITE_HEADERS = {"origin": "http://localhost:7843"}


@pytest.fixture(autouse=True)
def _reset_login_throttle(monkeypatch):
    import web.api.routes.auth as auth_mod

    snapshot_ts = auth_mod._last_login_ts
    sem_holder = auth_mod._login_sem
    snapshot_obj = sem_holder._obj
    snapshot_loop = sem_holder._loop
    monkeypatch.setattr(auth_mod, "_last_login_ts", 0.0)
    monkeypatch.setattr(auth_mod.time, "time", lambda: 10_000.0)
    yield
    auth_mod._last_login_ts = snapshot_ts
    sem_holder._obj = snapshot_obj
    sem_holder._loop = snapshot_loop


def test_login_cancelled_during_throttle_sleep_reraises(monkeypatch):
    import web.api.routes.auth as auth_mod
    from engine.auth.manager import auth_manager
    from web.api.models import LoginRequest
    from web.api.routes.auth import login

    monkeypatch.setattr(auth_mod, "_last_login_ts", 10_000.5)

    async def _cancel(_s):
        raise asyncio.CancelledError()

    monkeypatch.setattr(auth_mod.asyncio, "sleep", _cancel)

    login_calls = []

    async def _login(email, password):
        login_calls.append(1)
        return {"ok": True}

    monkeypatch.setattr(auth_manager, "login_async", _login)

    body = LoginRequest(pseudo="utilisateur_test", password="secret")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(login(body))
    assert login_calls == []


def test_login_http_exception_from_backend_propagates(monkeypatch):
    from fastapi import HTTPException

    import web.api.routes.auth as auth_mod
    from engine.auth.manager import auth_manager
    from web.api.models import LoginRequest
    from web.api.routes.auth import login

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(auth_mod.asyncio, "sleep", _no_sleep)

    async def _login(email, password):
        raise HTTPException(status_code=503, detail="backend unavailable")

    monkeypatch.setattr(auth_manager, "login_async", _login)

    body = LoginRequest(pseudo="utilisateur_test", password="secret")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(login(body))
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "backend unavailable"
