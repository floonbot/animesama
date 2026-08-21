import asyncio

import pytest

import engine.download.extractor.browser_extractor as be
import engine.download.interceptor as ic

_LOGS_JS = "window.__STREAM_LOGS__ || []"

JS_M3U8 = "https://cdn.example.com/secure/1/master.m3u8?token=js"
FRAME_M3U8 = "https://cdn.example.com/hls/frame/master.m3u8"
SHADOW_M3U8 = "https://cdn.example.com/shadow/master.m3u8"
RESP_M3U8 = "https://cdn.example.com/secure/9/master.m3u8?token=cdp"
REQ_PAGE_URL = "https://host.example.com/embed/player"


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


class FakePage:
    def __init__(
        self,
        cdp=None,
        content_html="",
        stream_logs=None,
        shadow_urls=None,
        child_frames=None,
    ):
        self._cdp = cdp
        self._content_html = content_html
        self._stream_logs = [] if stream_logs is None else stream_logs
        self._shadow_urls = [] if shadow_urls is None else shadow_urls
        self._child_frames = list(child_frames or [])
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
        if self._cdp is not None:
            self._cdp.fire_all()

    async def click(self, selector, timeout=None):
        self.click_calls.append((selector, timeout))
        raise RuntimeError("no play button")

    async def content(self):
        return self._content_html

    async def evaluate(self, js):
        self.evaluate_calls.append(js)
        if js == _LOGS_JS:
            return self._stream_logs
        if "scanShadow" in js:
            return self._shadow_urls
        return []

    async def close(self):
        self.closed = True


class FakeCdp:
    def __init__(self, events=None):
        self._events = events or []
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
        self.detached = True


class FakeCtx:
    def __init__(self, page):
        self._page = page
        self.closed = False
        self.init_scripts = []

    async def new_page(self):
        return self._page

    async def add_init_script(self, js):
        self.init_scripts.append(js)

    async def new_cdp_session(self, page):
        return self._page._cdp

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.contexts = []

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        ctx = FakeCtx(self._page)
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


def _patch_extractor(monkeypatch, browser):
    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "apply_stealth", _anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    monkeypatch.setattr(be.asyncio, "sleep", _anoop)


def test_standard_mode_finds_stream_via_stream_logs(monkeypatch):
    child = FakeFrame("http://host/child", stream_logs=[{"url": FRAME_M3U8}])
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        stream_logs=[{"url": JS_M3U8, "type": "js"}],
        shadow_urls=[],
        child_frames=[child],
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result["best"]["url"] == JS_M3U8
    urls = {entry["url"] for entry in result["all"]}
    assert JS_M3U8 in urls
    assert FRAME_M3U8 not in urls
    assert child.evaluate_calls == []


def test_standard_mode_captures_child_frame_stream(monkeypatch):
    child = FakeFrame("http://host/child", stream_logs=[{"url": FRAME_M3U8}])
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        stream_logs=[],
        shadow_urls=[],
        child_frames=[child],
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result["best"]["url"] == FRAME_M3U8
    frame_entries = [e for e in result["all"] if e["url"] == FRAME_M3U8]
    assert len(frame_entries) == 1
    assert frame_entries[0]["type"] == "frame"
    assert frame_entries[0]["source"] == "iframe"
    assert _LOGS_JS in child.evaluate_calls


def test_standard_mode_captures_shadow_dom_stream(monkeypatch):
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        stream_logs=[],
        shadow_urls=[SHADOW_M3U8],
        child_frames=[],
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result["best"]["url"] == SHADOW_M3U8
    shadow_entries = [e for e in result["all"] if e["url"] == SHADOW_M3U8]
    assert len(shadow_entries) == 1
    assert shadow_entries[0]["type"] == "shadow_dom"
    assert shadow_entries[0]["source"] == "shadow"


def test_fast_mode_skips_frame_and_shadow(monkeypatch):
    child = FakeFrame("http://host/child", stream_logs=[{"url": FRAME_M3U8, "type": "js"}])
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html>nothing here</html>",
        stream_logs=[],
        shadow_urls=[SHADOW_M3U8],
        child_frames=[child],
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="fast"))

    urls = {entry["url"] for entry in result["all"]}
    assert FRAME_M3U8 not in urls
    assert SHADOW_M3U8 not in urls
    assert result["best"] is None
    assert child.evaluate_calls == []
    assert not any("scanShadow" in js for js in page.evaluate_calls)


def test_cdp_request_response_headers_merged(monkeypatch):
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
    page = FakePage(
        cdp=cdp,
        content_html="<html></html>",
        stream_logs=[],
        shadow_urls=[],
        child_frames=[],
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result["best"]["url"] == RESP_M3U8
    headers = result["best"]["headers"]
    assert headers.get("X-Req") == "1"
    assert headers.get("X-Resp") == "2"
    timeline_entry = next(t for t in result["timeline"] if t["url"] == RESP_M3U8)
    assert timeline_entry["headers"] == {"X-Req": "1", "X-Resp": "2"}
    assert timeline_entry["type"] == "cdp_response"
    assert REQ_PAGE_URL not in {e["url"] for e in result["all"]}


def test_main_page_non_dict_stream_logs_are_skipped(monkeypatch):
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        stream_logs=["garbage", None, 123, ["x"], {"url": JS_M3U8, "type": "hlsjs"}],
        shadow_urls=[],
        child_frames=[],
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result["best"]["url"] == JS_M3U8
    assert {e["url"] for e in result["all"]} == {JS_M3U8}


def test_child_frame_non_dict_stream_logs_are_skipped(monkeypatch):
    child = FakeFrame(
        "http://host/child",
        stream_logs=["garbage", None, 123, {"url": FRAME_M3U8}],
    )
    page = FakePage(
        cdp=FakeCdp(events=[]),
        content_html="<html></html>",
        stream_logs=[],
        shadow_urls=[],
        child_frames=[child],
    )
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=2, mode="standard"))

    assert result["best"]["url"] == FRAME_M3U8
    assert _LOGS_JS in child.evaluate_calls


def test_lire_logs_frame_filters_non_dict_entries():
    frame = FakeFrame("http://host/x", stream_logs=["bad", None, 7, {"url": JS_M3U8}])
    out = asyncio.run(be._lire_logs_frame(frame))
    assert out == [{"url": JS_M3U8}]
