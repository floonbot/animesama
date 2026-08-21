import asyncio
import logging

import playwright.async_api as pw_api
import pytest

import engine.auth.manager as mgr_mod
import engine.cache.cover_images as ci
import engine.config.settings as settings_mod
import engine.download._rate_limiter as rl_mod
import engine.library.updates as updates_mod
import web.api.app as app_mod
import web.api.routes.health as health_mod
import web.api.routes.sse as sse_mod
from engine.config import logging_setup as ls
from engine.domain.exceptions import UnsafeUrlError
from engine.observability.metrics import Metrics
from engine.services.download_service import DownloadService

WRITE = {"origin": "http://localhost:7843"}


class _Sink:
    """Inner ASGI app recording the scope types it receives."""

    def __init__(self):
        self.events = []

    async def __call__(self, scope, receive, send):
        self.events.append(scope.get("type"))


async def _noop_receive():
    return {}


async def _noop_send(_message):
    return None


def test_security_headers_passes_non_http_scope_untouched():
    """SecurityHeaders forwards a non-HTTP scope without wrapping send (app.py 55-56)."""
    inner = _Sink()
    mw = app_mod.SecurityHeaders(inner)
    asyncio.run(mw({"type": "lifespan"}, _noop_receive, _noop_send))
    assert inner.events == ["lifespan"]


def test_cached_static_non_200_skips_cache_control(tmp_path, monkeypatch):
    """A non-200 response skips Cache-Control yet keeps base headers (app.py 107->116)."""
    from starlette.responses import Response

    static = app_mod.CachedStaticFiles(directory=str(tmp_path), html=True)

    async def _fake_super(self, path, scope):
        return Response(status_code=304, media_type="image/png")

    monkeypatch.setattr(
        app_mod.StaticFiles, "get_response", _fake_super, raising=True
    )
    resp = asyncio.run(static.get_response("logo.png", {"type": "http"}))
    assert resp.status_code == 304
    assert "cache-control" not in {k.lower() for k in resp.headers}
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "no-referrer"


def test_runtime_chromium_bundled_probe_exception_returns_false(monkeypatch):
    """A raising bundled_chromium_present probe yields False, not an exception (health.py 78-80)."""
    def _boom():
        raise RuntimeError("probe boom")

    monkeypatch.setattr(settings_mod, "bundled_chromium_present", _boom)
    assert health_mod._runtime_chromium_bundled() is False


class _FakeRequestStays:
    async def is_disconnected(self):
        return False


@pytest.fixture
def _sse_isolated():
    saved_loop = sse_mod._main_loop
    saved_event = sse_mod._shutdown_event
    with sse_mod._listeners_lock:
        saved_listeners = dict(sse_mod._listeners)
    saved_warn = dict(sse_mod._last_full_warn)
    yield
    sse_mod._main_loop = saved_loop
    sse_mod._shutdown_event = saved_event
    with sse_mod._listeners_lock:
        sse_mod._listeners.clear()
        sse_mod._listeners.update(saved_listeners)
    sse_mod._last_full_warn.clear()
    sse_mod._last_full_warn.update(saved_warn)


def test_stream_reuses_pending_get_task_across_iterations(monkeypatch, _sse_isolated):
    """A still-pending get_task is reused across two ping iterations (sse.py 96->98)."""
    real_wait = asyncio.wait

    async def _timeout_wait(waiters, timeout=None, return_when=None):
        return set(), set(waiters)

    async def scenario():
        with sse_mod._listeners_lock:
            sse_mod._listeners.clear()
        sse_mod.capture_loop_at_startup()
        resp = await sse_mod.events(_FakeRequestStays())
        agen = resp.body_iterator
        assert (await agen.__anext__()) == "retry: 3000\n"
        await agen.__anext__()
        await agen.__anext__()

        ensured = []
        original_ensure = asyncio.ensure_future

        def _spy_ensure(coro_or_future):
            fut = original_ensure(coro_or_future)
            name = getattr(getattr(coro_or_future, "cr_code", None), "co_name", "")
            if name == "get":
                ensured.append(fut)
            return fut

        monkeypatch.setattr(sse_mod.asyncio, "ensure_future", _spy_ensure)
        monkeypatch.setattr(sse_mod.asyncio, "wait", _timeout_wait)

        ping1 = await asyncio.wait_for(agen.__anext__(), timeout=3)
        ping2 = await asyncio.wait_for(agen.__anext__(), timeout=3)

        monkeypatch.setattr(sse_mod.asyncio, "wait", real_wait)
        await agen.aclose()
        return ping1, ping2, len([f for f in ensured if not f.cancelled()])

    ping1, ping2, get_creations = asyncio.run(scenario())
    assert ping1 == 'data: {"type": "ping"}\n\n'
    assert ping2 == 'data: {"type": "ping"}\n\n'
    assert get_creations == 1


def test_emit_with_no_listeners_skips_metrics(monkeypatch, _sse_isolated):
    """emit() with no listeners neither sends nor drops, skipping metrics (sse.py 165->exit)."""
    touched = []

    class _Boom:
        def incr(self, *a, **k):
            touched.append(("incr", a))

    monkeypatch.setattr("engine.observability.metrics.metrics", _Boom())

    async def scenario():
        with sse_mod._listeners_lock:
            sse_mod._listeners.clear()
        sse_mod.capture_loop_at_startup()
        sse_mod.emit("queue_updated", {"a": 1})
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert touched == []


def test_keepalive_skips_non_dict_and_nameless_cookies(monkeypatch):
    """keepalive_session ignores non-dict or nameless cookies (manager.py 86->85)."""
    monkeypatch.setattr(mgr_mod, "AuthStorage", lambda: object())
    mgr = mgr_mod.AuthManager()
    mgr._logged_in = True
    mgr.cookies = ["not-a-dict", {"value": "x"}, {"name": "sess", "value": "1"}]
    set_calls = []

    class _Jar:
        def set(self, name, value, **k):
            set_calls.append(name)

    class _Session:
        def __init__(self):
            self.headers = {}
            self.cookies = _Jar()

        def get(self, *a, **k):
            return mgr_mod.req.Response()

        def close(self):
            pass

    resp = mgr_mod.req.Response()
    resp.status_code = 200
    resp._content = b'{"logged_in": true}'

    sess = _Session()
    sess.get = lambda *a, **k: resp
    monkeypatch.setattr(mgr_mod.req, "Session", lambda: sess)
    assert mgr.keepalive_session() is True
    assert set_calls == ["sess"]


def test_logout_clear_cache_failure_swallowed(monkeypatch):
    """logout swallows a clear_session_cache failure (manager.py 333-334)."""
    import engine.scraping.scraper as scraper_mod

    class _Storage:
        def load_session(self):
            return None

    monkeypatch.setattr(mgr_mod, "AuthStorage", lambda: _Storage())
    mgr = mgr_mod.AuthManager()
    monkeypatch.setattr(mgr, "stop_keepalive_loop", lambda: None)
    mgr._logged_in = True
    mgr.cookies = [{"name": "x"}]

    def _boom():
        raise RuntimeError("cache boom")

    monkeypatch.setattr(scraper_mod, "clear_session_cache", _boom)
    mgr.logout()
    assert mgr.cookies == []
    assert mgr._logged_in is False


class _LoginPage:
    def __init__(self):
        self.click_calls = []
        self.fill_calls = []

    async def goto(self, *a, **k):
        pass

    async def wait_for_selector(self, sel, timeout=None):
        pass

    async def fill(self, sel, val):
        self.fill_calls.append((sel, val))

    async def click(self, sel):
        self.click_calls.append(sel)

    async def wait_for_url(self, pattern, timeout=None):
        pass


class _Ctx:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page

    async def cookies(self):
        return [{"name": "remember_token", "value": "323966:h"}]


class _Browser:
    def __init__(self, ctx):
        self._ctx = ctx
        self.close_calls = 0

    async def new_context(self, **kwargs):
        return self._ctx

    async def close(self):
        self.close_calls += 1


class _Chromium:
    def __init__(self, browser):
        self._browser = browser

    async def launch(self, **kwargs):
        return self._browser


class _PW:
    def __init__(self, browser):
        self.chromium = _Chromium(browser)


class _CM:
    def __init__(self, browser):
        self._browser = browser

    async def __aenter__(self):
        return _PW(self._browser)

    async def __aexit__(self, *exc):
        return False


def test_login_playwright_fills_new_form_and_submits(monkeypatch):
    """The new login form (#loginPseudo/#loginPassword) is filled and submitted; success via remember_token."""
    monkeypatch.setattr(mgr_mod, "AuthStorage", lambda: object())
    page = _LoginPage()
    browser = _Browser(_Ctx(page))
    monkeypatch.setattr(pw_api, "async_playwright", lambda: _CM(browser))
    result = asyncio.run(mgr_mod.AuthManager()._login_playwright("utilisateur_test", "pw"))
    assert result == {"ok": True, "cookies": [{"name": "remember_token", "value": "323966:h"}]}
    assert ("#loginPseudo", "utilisateur_test") in page.fill_calls
    assert page.click_calls == ["#formLogin button[type='submit']"]
    assert browser.close_calls == 1


def test_ep_est_ignore_non_dict_episodes_rule_returns_false():
    """A non-dict episodes_ignores value short-circuits to False (updates.py 58->65)."""
    regle = {"episodes_ignores": ["not", "a", "dict"]}
    assert updates_mod.ep_est_ignore(regle, 1, 5) is False


@pytest.fixture
def _updates_cache_clean():
    updates_mod.invalider_cache_updates()
    yield
    updates_mod.invalider_cache_updates()


def test_check_updates_skips_blank_favourite_name(monkeypatch, _updates_cache_clean):
    """A favourite with a blank normalised name is skipped when indexing (updates.py 112->110)."""
    import engine.library.scanner as scanner_mod
    import engine.scraping.scraper as scraper_mod

    monkeypatch.setattr(mgr_mod.auth_manager, "_logged_in", True)
    monkeypatch.setattr(
        scanner_mod,
        "scan_librairie_sync",
        lambda: {"animes": [{"nom": "Real Show", "saisons": []}]},
    )

    async def _favs():
        return [{"nom": "   ", "url": "http://x/blank"}, {"nom": "Other", "url": "http://x/o"}]

    monkeypatch.setattr(scraper_mod, "get_favorites_async", _favs)

    async def _eps(url, force_refresh=False):
        return {"episodes": []}

    monkeypatch.setattr(scraper_mod, "get_episodes_async", _eps)
    out = asyncio.run(updates_mod.check_updates_async())
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0


@pytest.fixture
def dl_service(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    svc = DownloadService()

    class _FakeQueue:
        def __init__(self):
            self.ajoutes = []

        async def ajouter(self, item):
            self.ajoutes.append(item)
            return len(self.ajoutes)

        def statut(self):
            return {}

    svc._queue = _FakeQueue()
    return svc


def test_ajouter_episode_skips_nameless_subepisodes(dl_service):
    """Sub-episodes that are not dicts or lack a titre are left untouched (download_service.py 27->26)."""
    item = {
        "ep": {"titre": "Anime", "saison": 1, "episode": 1},
        "episodes": ["not-a-dict", {"foo": "bar"}, {"titre": "Real/Title"}],
    }
    asyncio.run(dl_service.ajouter_episode(item))
    enqueued = dl_service._queue.ajoutes[0]["episodes"]
    assert enqueued[0] == "not-a-dict"
    assert enqueued[1] == {"foo": "bar"}
    assert "/" not in enqueued[2]["titre"]


def test_metrics_resume_detaille_supported_hosts_failure_defaults_empty():
    """A raising injected supported_hosts callable leaves hotes_supportes empty."""
    def _boom():
        raise RuntimeError("registry boom")

    out = Metrics().resume_detaille(supported_hosts=_boom)
    assert out["hotes_supportes"] == []


def test_cover_fetch_pin_target_unsafe_returns_none(monkeypatch):
    """fetch_and_store returns None when pin_target rejects the host (cover_images.py 79)."""
    monkeypatch.setattr(ci, "is_safe_url", lambda _u: True)

    def _boom(_url):
        raise UnsafeUrlError("blocked host")

    monkeypatch.setattr(ci, "pin_target", _boom)
    called = []
    monkeypatch.setattr(ci.requests, "get", lambda *a, **k: called.append(True))
    assert ci.fetch_and_store("https://cdn.example.com/x.jpg") is None
    assert called == []


@pytest.fixture
def _rate_limiter_clean():
    snap = dict(rl_mod._domain_last_access)
    yield
    rl_mod._domain_last_access.clear()
    rl_mod._domain_last_access.update(snap)


def test_purge_cache_no_expired_entries_exits_quietly(monkeypatch, _rate_limiter_clean, caplog):
    """Purging with only fresh entries logs and removes nothing (_rate_limiter.py 67->exit)."""
    rl_mod._domain_last_access.clear()
    monkeypatch.setattr(rl_mod.time, "time", lambda: 1_000_000.0)
    rl_mod._domain_last_access["fresh.example"] = 1_000_000.0
    with caplog.at_level(logging.DEBUG, logger="engine.download.rate_limiter"):
        rl_mod._purger_cache_verrou_tenu()
    assert "fresh.example" in rl_mod._domain_last_access
    assert not any("expirée" in r.getMessage() for r in caplog.records)


@pytest.fixture
def _logger_level_clean():
    lg = logging.getLogger("test_success_disabled_gap")
    saved = lg.level
    yield lg
    lg.setLevel(saved)


def test_success_log_skipped_when_level_disabled(_logger_level_clean):
    """logger.success does not emit when SUCCESS is disabled (logging_setup.py 68->exit)."""
    lg = _logger_level_clean
    lg.setLevel(logging.ERROR)
    emitted = []
    original_log = lg._log
    lg._log = lambda *a, **k: emitted.append(a)
    try:
        ls._log_success(lg, "should be dropped")
    finally:
        lg._log = original_log
    assert emitted == []