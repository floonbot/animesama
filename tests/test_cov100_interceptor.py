import asyncio
import importlib.util
import logging
import sys
import types

import pytest

import engine.download.interceptor as ic


async def _anoop(*args, **kwargs):
    return None


def _snapshot_globals():
    return {
        "sem": ic._ctx_semaphore_state["sem"],
        "sem_loop": ic._ctx_semaphore_state["loop"],
        "lock": ic._browser_lock_state["lock"],
        "lock_loop": ic._browser_lock_state["loop"],
        "browser": ic._browser,
        "playwright": ic._playwright,
        "default_handler": ic._default_exception_handler,
        "installed": set(ic._handler_installed_on_loop),
        "stealth_fn": ic._stealth_fn,
        "stealth_available": ic._STEALTH_AVAILABLE,
        "stealth_instance": getattr(ic, "_stealth_instance", None),
    }


def _restore_globals(snap):
    ic._ctx_semaphore_state["sem"] = snap["sem"]
    ic._ctx_semaphore_state["loop"] = snap["sem_loop"]
    ic._browser_lock_state["lock"] = snap["lock"]
    ic._browser_lock_state["loop"] = snap["lock_loop"]
    ic._browser = snap["browser"]
    ic._playwright = snap["playwright"]
    ic._default_exception_handler = snap["default_handler"]
    ic._handler_installed_on_loop.clear()
    for loop in snap["installed"]:
        ic._handler_installed_on_loop.add(loop)
    ic._stealth_fn = snap["stealth_fn"]
    ic._STEALTH_AVAILABLE = snap["stealth_available"]
    if snap["stealth_instance"] is not None:
        ic._stealth_instance = snap["stealth_instance"]


@pytest.fixture(autouse=True)
def _isolate_globals():
    snap = _snapshot_globals()
    ic._ctx_semaphore_state["sem"] = None
    ic._ctx_semaphore_state["loop"] = None
    ic._browser_lock_state["lock"] = None
    ic._browser_lock_state["loop"] = None
    ic._browser = None
    ic._playwright = None
    ic._default_exception_handler = None
    ic._handler_installed_on_loop.clear()
    yield
    _restore_globals(snap)


class FakeRequest:
    def __init__(self, url, headers=None, headers_raises=False, url_raises=False):
        self._url = url
        self._headers = headers or {}
        self._headers_raises = headers_raises
        self._url_raises = url_raises

    @property
    def url(self):
        if self._url_raises:
            raise RuntimeError("url boom")
        return self._url

    @property
    def headers(self):
        if self._headers_raises:
            raise RuntimeError("headers boom")
        return self._headers


class FakePage:
    def __init__(self, requests=None, goto_exc=None, close_exc=None):
        self._requests = requests or []
        self._goto_exc = goto_exc
        self._close_exc = close_exc
        self._handlers = {}
        self.closed = False
        self.goto_calls = []
        self.url = "https://fake.local/"
        self.frames = [self]

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    async def goto(self, *args, **kwargs):
        self.goto_calls.append(kwargs)
        if self._goto_exc is not None:
            raise self._goto_exc
        for handler in self._handlers.get("request", []):
            for req in self._requests:
                handler(req)

    async def click(self, selector, timeout=None):
        raise RuntimeError("no play button")

    async def close(self):
        self.closed = True
        if self._close_exc is not None:
            raise self._close_exc


class FakeCtx:
    def __init__(self, page, close_exc=None):
        self._page = page
        self.closed = False
        self._close_exc = close_exc

    async def new_page(self):
        return self._page

    async def close(self):
        self.closed = True
        if self._close_exc is not None:
            raise self._close_exc


class FakeBrowser:
    def __init__(self, page, ctx_close_exc=None):
        self._page = page
        self._ctx_close_exc = ctx_close_exc
        self.contexts = []

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        ctx = FakeCtx(self._page, close_exc=self._ctx_close_exc)
        self.contexts.append(ctx)
        return ctx


def _patch_interceptor(monkeypatch, browser):
    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "_get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "_appliquer_stealth", _anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    monkeypatch.setattr(ic.asyncio, "sleep", _anoop)


def test_appliquer_stealth_calls_v2_apply(monkeypatch):
    seen = []

    class _Inst:
        async def apply_stealth_async(self, page):
            seen.append(page)

    monkeypatch.setattr(ic, "_stealth_instance", _Inst())
    monkeypatch.setattr(ic, "_STEALTH_AVAILABLE", True)
    monkeypatch.setattr(ic, "_stealth_fn", ic._stealth_fn_v2)

    sentinel = object()
    asyncio.run(ic._appliquer_stealth(sentinel))

    assert seen == [sentinel]


def test_appliquer_stealth_disabled_returns_early(monkeypatch):
    monkeypatch.setattr(ic, "_STEALTH_AVAILABLE", False)
    monkeypatch.setattr(ic, "_stealth_fn", None)

    asyncio.run(ic._appliquer_stealth(object()))


def test_appliquer_stealth_swallows_exception(monkeypatch, caplog):
    async def _boom(page):
        raise RuntimeError("stealth fail")

    monkeypatch.setattr(ic, "_STEALTH_AVAILABLE", True)
    monkeypatch.setattr(ic, "_stealth_fn", _boom)

    with caplog.at_level(logging.DEBUG, logger="engine.download.interceptor"):
        asyncio.run(ic._appliquer_stealth(object()))

    assert any("Stealth échoué" in rec.message for rec in caplog.records)


def test_get_browser_wrapper_delegates(monkeypatch):
    sentinel = object()

    async def _fake():
        return sentinel

    monkeypatch.setattr(ic, "_get_browser", _fake)

    assert asyncio.run(ic.get_browser()) is sentinel


def test_apply_stealth_wrapper_delegates(monkeypatch):
    seen = []

    async def _fake(page):
        seen.append(page)

    monkeypatch.setattr(ic, "_appliquer_stealth", _fake)

    sentinel = object()
    asyncio.run(ic.apply_stealth(sentinel))

    assert seen == [sentinel]


def test_ctx_semaphore_outside_loop_raises():
    with pytest.raises(RuntimeError):
        ic._ctx_semaphore()


def test_browser_lock_outside_loop_raises():
    with pytest.raises(RuntimeError):
        ic._browser_lock()


def test_install_loop_exception_handler_outside_loop_returns():
    ic._install_loop_exception_handler()
    assert ic._default_exception_handler is None


def test_custom_handler_one_arg_raises_generic_then_logs(monkeypatch, caplog):
    def _bad(ctx):
        raise ValueError("not a typeerror")

    monkeypatch.setattr(ic, "_default_exception_handler", _bad)

    with caplog.at_level(logging.ERROR, logger="engine.download.interceptor"):
        ic._custom_exception_handler(object(), {"message": "real", "exception": KeyError("x")})

    assert any(rec.levelno == logging.ERROR for rec in caplog.records)


def test_custom_handler_two_arg_fallback_also_raises_then_logs(monkeypatch, caplog):
    def _bad(*args):
        if len(args) == 1:
            raise TypeError("need two")
        raise RuntimeError("two-arg also broken")

    monkeypatch.setattr(ic, "_default_exception_handler", _bad)

    with caplog.at_level(logging.ERROR, logger="engine.download.interceptor"):
        ic._custom_exception_handler(object(), {"message": "real", "exception": KeyError("x")})

    assert any(rec.levelno == logging.ERROR for rec in caplog.records)


def test_est_bruit_attendu_via_mro_ancestor():
    class _Sub(asyncio.CancelledError):
        pass

    assert ic._est_bruit_attendu({"exception": _Sub()}) is True


def test_est_bruit_attendu_via_exception_str_pattern():
    exc = RuntimeError("Target closed")
    assert ic._est_bruit_attendu({"exception": exc}) is True


def test_is_browser_alive_none_and_raising_and_true():
    assert ic._is_browser_alive(None) is False

    class _Boom:
        def is_connected(self):
            raise RuntimeError("disconnected")

    assert ic._is_browser_alive(_Boom()) is False

    class _Ok:
        def is_connected(self):
            return True

    assert ic._is_browser_alive(_Ok()) is True


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser
        self.launch_kwargs = None

    async def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self._browser


class _FakePlaywright:
    def __init__(self, browser, stop_exc=None):
        self.chromium = _FakeChromium(browser)
        self.stopped = False
        self._stop_exc = stop_exc

    async def stop(self):
        self.stopped = True
        if self._stop_exc is not None:
            raise self._stop_exc


class _FakeAsyncPlaywrightCM:
    def __init__(self, pw):
        self._pw = pw

    async def start(self):
        return self._pw


def _install_fake_async_playwright(monkeypatch, pw):
    import playwright.async_api as pa

    def _factory():
        return _FakeAsyncPlaywrightCM(pw)

    monkeypatch.setattr(pa, "async_playwright", _factory)


def test_get_browser_returns_existing_alive(monkeypatch):
    monkeypatch.setattr(ic, "_install_loop_exception_handler", lambda: None)

    class _Alive:
        def is_connected(self):
            return True

    alive = _Alive()
    ic._browser = alive

    result = asyncio.run(ic._get_browser())

    assert result is alive


def test_get_browser_launches_fresh(monkeypatch):
    monkeypatch.setattr(ic, "_install_loop_exception_handler", lambda: None)
    fake_browser = object()
    pw = _FakePlaywright(fake_browser)
    _install_fake_async_playwright(monkeypatch, pw)

    ic._browser = None
    ic._playwright = None

    result = asyncio.run(ic._get_browser())

    assert result is fake_browser
    assert ic._browser is fake_browser
    assert ic._playwright is pw
    assert pw.chromium.launch_kwargs is not None


class _FakeChromiumFails:
    async def launch(self, **kwargs):
        raise RuntimeError("chromium binary missing")


class _FakePlaywrightLaunchFails:
    def __init__(self):
        self.chromium = _FakeChromiumFails()
        self.stopped = False

    async def stop(self):
        self.stopped = True


def test_get_browser_stops_playwright_on_launch_failure(monkeypatch):
    monkeypatch.setattr(ic, "_install_loop_exception_handler", lambda: None)
    pw = _FakePlaywrightLaunchFails()
    _install_fake_async_playwright(monkeypatch, pw)

    ic._browser = None
    ic._playwright = None

    async def scenario():
        with pytest.raises(RuntimeError):
            await ic._get_browser()

    asyncio.run(scenario())

    assert pw.stopped is True
    assert ic._playwright is None
    assert ic._browser is None


def test_get_browser_stops_stale_playwright_then_relaunch(monkeypatch):
    monkeypatch.setattr(ic, "_install_loop_exception_handler", lambda: None)
    fresh_browser = object()
    new_pw = _FakePlaywright(fresh_browser)
    _install_fake_async_playwright(monkeypatch, new_pw)

    stale_pw = _FakePlaywright(object(), stop_exc=RuntimeError("stop fail"))

    class _Dead:
        def is_connected(self):
            return False

    ic._browser = _Dead()
    ic._playwright = stale_pw

    result = asyncio.run(ic._get_browser())

    assert stale_pw.stopped is True
    assert result is fresh_browser
    assert ic._playwright is new_pw


def test_reset_browser_apres_erreur_closes_and_stops(monkeypatch):
    closed = {"b": False, "pw": False}

    class _B:
        async def close(self):
            closed["b"] = True

    class _PW:
        async def stop(self):
            closed["pw"] = True

    ic._browser = _B()
    ic._playwright = _PW()

    asyncio.run(ic._reset_browser_apres_erreur())

    assert closed == {"b": True, "pw": True}
    assert ic._browser is None
    assert ic._playwright is None


def test_reset_browser_apres_erreur_swallows_errors(monkeypatch, caplog):
    class _B:
        async def close(self):
            raise RuntimeError("close boom")

    class _PW:
        async def stop(self):
            raise RuntimeError("stop boom")

    ic._browser = _B()
    ic._playwright = _PW()

    with caplog.at_level(logging.DEBUG, logger="engine.download.interceptor"):
        asyncio.run(ic._reset_browser_apres_erreur())

    assert ic._browser is None
    assert ic._playwright is None
    msgs = " ".join(rec.message for rec in caplog.records)
    assert "reset/close browser" in msgs
    assert "reset/stop playwright" in msgs


def test_fermer_browser_calls_reset(monkeypatch):
    called = []

    async def _reset():
        called.append(True)

    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _reset)
    monkeypatch.setattr(ic.asyncio, "sleep", _anoop)

    asyncio.run(ic.fermer_browser())

    assert called == [True]


def test_fermer_browser_swallows_sleep_error(monkeypatch):
    async def _reset():
        return None

    async def _bad_sleep(*a, **k):
        raise RuntimeError("sleep boom")

    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _reset)
    monkeypatch.setattr(ic.asyncio, "sleep", _bad_sleep)

    asyncio.run(ic.fermer_browser())


def test_intercepter_lecteur_bad_timeout_defaults(monkeypatch):
    page = FakePage(requests=[FakeRequest("https://cdn.example.com/master.m3u8", {"h": "1"})])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=object()))

    assert result["url"] == "https://cdn.example.com/master.m3u8"


def test_on_request_empty_url_is_ignored(monkeypatch):
    page = FakePage(requests=[FakeRequest("")])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result is None


def test_on_request_headers_raise_uses_empty_dict(monkeypatch):
    page = FakePage(requests=[
        FakeRequest("https://cdn.example.com/master.m3u8", headers_raises=True),
    ])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result["url"] == "https://cdn.example.com/master.m3u8"
    assert result["headers"] == {}


def test_on_request_url_access_raises_is_swallowed(monkeypatch, caplog):
    page = FakePage(requests=[FakeRequest("ignored", url_raises=True)])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    with caplog.at_level(logging.DEBUG, logger="engine.download.interceptor"):
        result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result is None
    assert any("on_request handler error" in rec.message for rec in caplog.records)


def test_goto_cancelled_propagates(monkeypatch):
    page = FakePage(goto_exc=asyncio.CancelledError())
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert page.closed is True


def test_page_close_error_is_swallowed(monkeypatch, caplog):
    page = FakePage(
        requests=[FakeRequest("https://cdn.example.com/master.m3u8", {"h": "1"})],
        close_exc=RuntimeError("page close boom"),
    )
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    with caplog.at_level(logging.DEBUG, logger="engine.download.interceptor"):
        result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result["url"] == "https://cdn.example.com/master.m3u8"
    assert any("page.close()" in rec.message for rec in caplog.records)


def test_ctx_close_error_is_swallowed(monkeypatch, caplog):
    page = FakePage(requests=[FakeRequest("https://cdn.example.com/master.m3u8", {"h": "1"})])
    browser = FakeBrowser(page, ctx_close_exc=RuntimeError("ctx close boom"))
    _patch_interceptor(monkeypatch, browser)

    with caplog.at_level(logging.DEBUG, logger="engine.download.interceptor"):
        result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result["url"] == "https://cdn.example.com/master.m3u8"
    assert any("ctx.close()" in rec.message for rec in caplog.records)


class _ClickPage:
    def __init__(self, click_exc_factory):
        self._click_exc_factory = click_exc_factory
        self.click_calls = []
        self.url = "https://fake.local/"
        self.frames = [self]

    async def query_selector(self, selector):
        return object()

    async def click(self, selector, timeout=None):
        self.click_calls.append(selector)
        raise self._click_exc_factory(selector)


def test_tenter_clic_play_cancelled_propagates():
    def _raise(selector):
        return asyncio.CancelledError()

    page = _ClickPage(_raise)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ic._tenter_clic_play(page))

    assert len(page.click_calls) == 1


def test_tenter_clic_play_pwerror_not_closed_continues():
    from playwright.async_api import Error as PWError

    def _raise(selector):
        return PWError("element not found")

    page = _ClickPage(_raise)

    asyncio.run(ic._tenter_clic_play(page))

    assert page.click_calls == list(ic.PLAY_SELECTORS)


def test_tenter_clic_play_importerror_fallback(monkeypatch):
    real_mod = sys.modules.get("playwright.async_api")
    shim = types.ModuleType("playwright.async_api")
    monkeypatch.setitem(sys.modules, "playwright.async_api", shim)

    def _raise(selector):
        return RuntimeError("generic")

    page = _ClickPage(_raise)

    try:
        asyncio.run(ic._tenter_clic_play(page))
    finally:
        if real_mod is not None:
            sys.modules["playwright.async_api"] = real_mod

    assert page.click_calls == list(ic.PLAY_SELECTORS)


def test_parallele_coro_cancelled_propagates(monkeypatch):
    monkeypatch.setattr(ic, "_install_loop_exception_handler", lambda: None)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)

    async def _stub(src, timeout=8, _in_parallel=False):
        raise asyncio.CancelledError()

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ic.intercepter_lecteurs_parallele([{"src": "http://a"}], timeout=2))


def _load_fresh_interceptor(fake_stealth_module):
    spec = importlib.util.spec_from_file_location(
        "_interceptor_fresh_probe", ic.__file__
    )
    module = importlib.util.module_from_spec(spec)
    saved = sys.modules.get("playwright_stealth")
    try:
        if fake_stealth_module is None:
            sys.modules.pop("playwright_stealth", None)
        else:
            sys.modules["playwright_stealth"] = fake_stealth_module
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["playwright_stealth"] = saved
        else:
            sys.modules.pop("playwright_stealth", None)
    return module


def test_module_import_both_stealth_imports_fail():
    empty = types.ModuleType("playwright_stealth")
    module = _load_fresh_interceptor(empty)

    assert module._STEALTH_AVAILABLE is False
    assert module._stealth_fn is None
