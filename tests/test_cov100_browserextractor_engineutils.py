import asyncio

import pytest

import engine.download._engine_utils as u
import engine.download.extractor.browser_extractor as be
import engine.download.interceptor as ic
import engine.download.methods._proc_registry as pr

_LOGS_JS = "window.__STREAM_LOGS__ || []"

REQ_PAGE_URL = "https://host.example.com/embed/player"
RESP_M3U8 = "https://cdn.example.com/secure/9/master.m3u8?token=cdp"


class FakeFrame:
    def __init__(self, url, stream_logs=None):
        self.url = url
        self._stream_logs = [] if stream_logs is None else stream_logs
        self.evaluate_calls = []

    async def evaluate(self, js):
        self.evaluate_calls.append(js)
        if js == _LOGS_JS:
            return self._stream_logs
        return []


class FakeCdp:
    def __init__(self, events=None, detach_raises=None):
        self._events = events or []
        self._detach_raises = detach_raises
        self._handlers = {}
        self.sent = []
        self.detached = False

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def fire_all(self):
        for event, params in self._events:
            for handler in self._handlers.get(event, []):
                handler(params)

    async def detach(self):
        if self._detach_raises is not None:
            raise self._detach_raises
        self.detached = True


class FakePage:
    def __init__(
        self,
        cdp=None,
        content_html="",
        stream_logs=None,
        shadow_urls=None,
        shadow_raises=None,
        child_frames=None,
        goto_raises=None,
        click_raises=None,
        click_succeeds=False,
        close_raises=None,
    ):
        self._cdp = cdp
        self._content_html = content_html
        self._stream_logs = [] if stream_logs is None else stream_logs
        self._shadow_urls = [] if shadow_urls is None else shadow_urls
        self._shadow_raises = shadow_raises
        self._child_frames = list(child_frames or [])
        self._goto_raises = goto_raises
        self._click_raises = click_raises
        self._click_succeeds = click_succeeds
        self._close_raises = close_raises
        self._handlers = {}
        self.main_frame = self
        self.url = "http://host/main"
        self.closed = False
        self.goto_calls = []
        self.click_calls = []
        self.evaluate_calls = []

    @property
    def frames(self):
        return [self.main_frame, *self._child_frames]

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    async def goto(self, *args, **kwargs):
        self.goto_calls.append(kwargs)
        if self._goto_raises is not None:
            raise self._goto_raises
        if self._cdp is not None:
            self._cdp.fire_all()

    async def click(self, selector, timeout=None):
        self.click_calls.append((selector, timeout))
        if self._click_raises is not None:
            raise self._click_raises
        if self._click_succeeds:
            return None
        raise RuntimeError("no play button")

    async def content(self):
        return self._content_html

    async def evaluate(self, js):
        self.evaluate_calls.append(js)
        if js == _LOGS_JS:
            return self._stream_logs
        if "scanShadow" in js:
            if self._shadow_raises is not None:
                raise self._shadow_raises
            return self._shadow_urls
        return []

    async def close(self):
        if self._close_raises is not None:
            raise self._close_raises
        self.closed = True


class FakeCtx:
    def __init__(self, page, close_raises=None):
        self._page = page
        self._close_raises = close_raises
        self.closed = False
        self.init_scripts = []

    async def new_page(self):
        return self._page

    async def add_init_script(self, js):
        self.init_scripts.append(js)

    async def new_cdp_session(self, page):
        return self._page._cdp

    async def close(self):
        if self._close_raises is not None:
            raise self._close_raises
        self.closed = True


class FakeBrowser:
    def __init__(self, page, ctx_close_raises=None):
        self._page = page
        self._ctx_close_raises = ctx_close_raises
        self.contexts = []

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        ctx = FakeCtx(self._page, close_raises=self._ctx_close_raises)
        self.contexts.append(ctx)
        return ctx


async def _anoop(*args, **kwargs):
    return None


def _reset_interceptor_globals():
    ic._ctx_semaphore_state["sem"] = None
    ic._ctx_semaphore_state["loop"] = None
    ic._browser = None
    ic._playwright = None


@pytest.fixture(autouse=True)
def _isolate_globals():
    _reset_interceptor_globals()
    yield
    _reset_interceptor_globals()


def _patch_extractor(monkeypatch, browser, reset_recorder=None, reset_raises=None):
    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "apply_stealth", _anoop)
    monkeypatch.setattr(be.asyncio, "sleep", _anoop)
    if reset_raises is not None:
        async def _raise_reset(*args, **kwargs):
            raise reset_raises

        monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _raise_reset)
    elif reset_recorder is None:
        monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    else:
        async def _record_reset(*args, **kwargs):
            reset_recorder.append(True)

        monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _record_reset)


def test_extraire_flux_non_numeric_timeout_defaults(monkeypatch):
    page = FakePage(cdp=FakeCdp(events=[]), content_html="<html></html>")
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout="abc", mode="fast"))

    assert result["best"] is None
    assert page.goto_calls


def test_extraire_flux_cdp_headers_overflow_evicts_oldest(monkeypatch):
    monkeypatch.setattr(be, "_CDP_HDRS_MAX", 2)
    events = [
        (
            "Network.requestWillBeSent",
            {"requestId": f"r{i}", "request": {"url": f"https://h/a{i}", "headers": {"k": str(i)}}},
        )
        for i in range(3)
    ]
    cdp = FakeCdp(events=events)
    page = FakePage(cdp=cdp, content_html="<html></html>")
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    assert result["best"] is None
    assert page.goto_calls


def test_extraire_flux_cdp_request_handler_swallows_error(monkeypatch):
    events = [("Network.requestWillBeSent", None)]
    cdp = FakeCdp(events=events)
    page = FakePage(cdp=cdp, content_html="<html></html>")
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    assert result["best"] is None


def test_extraire_flux_cdp_response_handler_swallows_error(monkeypatch):
    events = [("Network.responseReceived", None)]
    cdp = FakeCdp(events=events)
    page = FakePage(cdp=cdp, content_html="<html></html>")
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    assert result["best"] is None


def test_extraire_flux_goto_generic_exception_is_logged(monkeypatch):
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        goto_raises=RuntimeError("navigation failed"),
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    assert result["best"] is None
    assert page.goto_calls


def test_extraire_flux_goto_cancelled_propagates(monkeypatch):
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        goto_raises=asyncio.CancelledError(),
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    assert page.click_calls == []


def test_extraire_flux_click_success_breaks_loop(monkeypatch):
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        click_succeeds=True,
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    assert result["best"] is None
    assert len(page.click_calls) == 1


def test_extraire_flux_click_cancelled_propagates(monkeypatch):
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        click_raises=asyncio.CancelledError(),
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    assert len(page.click_calls) == 1


def test_extraire_flux_shadow_scan_exception_is_logged(monkeypatch):
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        shadow_raises=RuntimeError("shadow boom"),
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result["best"] is None
    assert any("scanShadow" in js for js in page.evaluate_calls)


def test_extraire_flux_cleanup_exceptions_are_swallowed(monkeypatch):
    cdp = FakeCdp(events=[], detach_raises=RuntimeError("detach boom"))
    page = FakePage(
        cdp=cdp,
        content_html="<html></html>",
        close_raises=RuntimeError("page close boom"),
    )
    browser = FakeBrowser(page, ctx_close_raises=RuntimeError("ctx close boom"))
    _patch_extractor(monkeypatch, browser)

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    assert result["best"] is None
    assert page.goto_calls


def test_extraire_flux_grave_error_reset_exception_is_swallowed(monkeypatch):
    page = FakePage(cdp=FakeCdp(events=[]))

    class _ClosingBrowser(FakeBrowser):
        async def new_context(self, **kwargs):
            raise RuntimeError("Target page, context or browser has been closed")

    browser = _ClosingBrowser(page)
    _patch_extractor(monkeypatch, browser, reset_raises=RuntimeError("reset boom"))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result == {"best": None, "all": [], "timeline": []}


def test_extraire_flux_cdp_request_response_headers_round_trip(monkeypatch):
    events = [
        (
            "Network.requestWillBeSent",
            {"requestId": "r1", "request": {"url": REQ_PAGE_URL, "headers": {"X-Req": "1"}}},
        ),
        (
            "Network.responseReceived",
            {"requestId": "r1", "response": {"url": RESP_M3U8, "headers": {"X-Resp": "2"}}},
        ),
    ]
    cdp = FakeCdp(events=events)
    page = FakePage(cdp=cdp, content_html="<html></html>")
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result["best"]["url"] == RESP_M3U8
    assert result["best"]["headers"].get("X-Req") == "1"
    assert result["best"]["headers"].get("X-Resp") == "2"


class _KillProc:
    def __init__(self, pid=777):
        self.pid = pid

    def poll(self):
        return None

    def terminate(self):
        raise RuntimeError("cannot terminate")

    def kill(self):
        raise RuntimeError("cannot kill")


def test_terminate_tree_kill_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(u.os, "name", "posix")
    proc = _KillProc()
    u.terminate_tree(proc)


def test_est_url_http_urlparse_exception_returns_false(monkeypatch):
    def _boom(_url):
        raise ValueError("bad url")

    monkeypatch.setattr(u, "urlparse", _boom)
    assert u.est_url_http("http://host/x") is False


class _WatchdogProc:
    def __init__(self, poll_raises=False):
        self.pid = 4321
        self._poll_raises = poll_raises

    def poll(self):
        if self._poll_raises:
            raise RuntimeError("poll boom")
        return None


class _FakeThread:
    instances = []

    def __init__(self, target=None, daemon=None, name=None, **kwargs):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        _FakeThread.instances.append(self)

    def start(self):
        self.started = True


class _ScriptedWait:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    def __call__(self, timeout):
        self.calls.append(timeout)
        if self.scripted:
            return self.scripted.pop(0)
        return True


def test_watchdog_inner_exception_logs_and_returns(monkeypatch):
    _FakeThread.instances = []
    monkeypatch.setattr(u.threading, "Thread", _FakeThread)
    killed = []
    monkeypatch.setattr(u, "terminate_tree", lambda p: killed.append(p))
    monkeypatch.setattr(pr, "is_suspended", lambda p: False)

    proc = _WatchdogProc(poll_raises=True)
    stop = u.spawn_proc_watchdog(proc, None, 10.0)
    monkeypatch.setattr(stop, "wait", _ScriptedWait([False]))

    thread = _FakeThread.instances[0]
    assert thread.started is True

    thread.target()

    assert killed == []


class _RegProc:
    def __init__(self, pid=555):
        self.pid = pid

    def poll(self):
        return None


def test_register_proc_during_cancel_terminate_raises_is_swallowed(monkeypatch):
    actifs_snap = set(pr._actifs)
    cancel_snap = pr._cancel_en_cours
    pr._actifs.clear()
    pr._cancel_en_cours = True

    def _boom(proc):
        raise RuntimeError("terminate boom")

    monkeypatch.setattr(u, "terminate_tree", _boom)
    try:
        proc = _RegProc()
        pr.register_proc(proc)
        assert proc not in pr._actifs
    finally:
        pr._actifs.clear()
        pr._actifs.update(actifs_snap)
        pr._cancel_en_cours = cancel_snap
