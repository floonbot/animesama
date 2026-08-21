import asyncio

import pytest

import engine.download.extractor.browser_extractor as be
import engine.download.interceptor as ic

M3U8_URL = "https://cdn.example.com/secure/1/master.m3u8?token=abc"
TXT_URL = "https://cdn.example.com/master.txt"
NON_STREAM_URL = "https://cdn.example.com/player.js"
DENYLISTED_STREAM_URL = "https://tracker.example.com/master.m3u8"


class FakeRequest:
    def __init__(self, url, headers=None):
        self.url = url
        self.headers = headers or {}


class FakePage:
    def __init__(self, requests=None, content_html="", cdp=None, evaluate_result=None):
        self._requests = requests or []
        self._content_html = content_html
        self._cdp = cdp
        self._evaluate_result = [] if evaluate_result is None else evaluate_result
        self._handlers = {}
        self.main_frame = self
        self.url = "http://host/main"
        self.closed = False
        self.goto_calls = []
        self.click_calls = []

    @property
    def frames(self):
        return [self.main_frame]

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    async def goto(self, *args, **kwargs):
        self.goto_calls.append(kwargs)
        for handler in self._handlers.get("request", []):
            for req in self._requests:
                handler(req)
        if self._cdp is not None:
            self._cdp.fire_all()

    async def click(self, selector, timeout=None):
        self.click_calls.append((selector, timeout))
        raise RuntimeError("no play button")

    async def content(self):
        return self._content_html

    async def evaluate(self, js):
        return self._evaluate_result

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


def _patch_interceptor(monkeypatch, browser):
    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "_get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "_appliquer_stealth", _anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    monkeypatch.setattr(ic.asyncio, "sleep", _anoop)


def test_intercepter_lecteur_invalid_url_returns_none(monkeypatch):
    page = FakePage()
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteur("ftp://not-http/here", timeout=2))

    assert result is None
    assert page.goto_calls == []


def test_intercepter_lecteur_captures_m3u8(monkeypatch):
    page = FakePage(requests=[FakeRequest(M3U8_URL, {"x-auth": "1"})])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result == {"url": M3U8_URL, "headers": {"x-auth": "1"}}
    assert page.closed is True


def test_intercepter_lecteur_ignores_non_stream_url(monkeypatch):
    """A non-stream resource (no m3u8/stream pattern) is dropped by url_est_stream."""
    page = FakePage(requests=[FakeRequest(NON_STREAM_URL, {"a": "b"})])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result is None


def test_intercepter_lecteur_drops_denylisted_stream_url(monkeypatch):
    """A URL that IS a stream (.m3u8) but is on the denylist (tracker) is dropped by url_a_ignorer."""
    page = FakePage(requests=[FakeRequest(DENYLISTED_STREAM_URL, {"a": "b"})])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result is None


def test_intercepter_lecteur_m3u8_wins_over_txt(monkeypatch):
    page = FakePage(requests=[
        FakeRequest(TXT_URL, {"k": "txt"}),
        FakeRequest(M3U8_URL, {"k": "m3u8"}),
    ])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result["url"] == M3U8_URL
    assert result["headers"] == {"k": "m3u8"}


def test_intercepter_lecteurs_parallele_returns_found_stream(monkeypatch):
    page = FakePage(requests=[FakeRequest(M3U8_URL, {"h": "1"})])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    lecteurs = [
        {"src": "http://host/embed1"},
        {"src": "http://host/embed2"},
    ]
    result = asyncio.run(ic.intercepter_lecteurs_parallele(lecteurs, timeout=2))

    assert result["url"] == M3U8_URL


def test_intercepter_lecteurs_parallele_empty_is_none(monkeypatch):
    page = FakePage()
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    assert asyncio.run(ic.intercepter_lecteurs_parallele([], timeout=2)) is None


def test_intercepter_lecteurs_parallele_no_src_is_none(monkeypatch):
    page = FakePage()
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(ic.intercepter_lecteurs_parallele([{"foo": "bar"}], timeout=2))

    assert result is None


def _patch_extractor(monkeypatch, browser):
    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "apply_stealth", _anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    monkeypatch.setattr(be.asyncio, "sleep", _anoop)


def test_extraire_flux_forensic_extracts_m3u8_from_content(monkeypatch):
    html = f'<html><body><script>var s="{M3U8_URL}";</script></body></html>'
    cdp = FakeCdp(events=[])
    page = FakePage(content_html=html, cdp=cdp)
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="forensic"))

    assert result["best"] is not None
    assert result["best"]["url"] == M3U8_URL
    assert page.closed is True
    assert cdp.detached is True


def test_extraire_flux_forensic_no_m3u8_best_is_none(monkeypatch):
    html = "<html><body>nothing relevant here</body></html>"
    cdp = FakeCdp(events=[])
    page = FakePage(content_html=html, cdp=cdp)
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="forensic"))

    assert result["best"] is None
    assert result["all"] == []


def test_extraire_flux_invalid_url_returns_empty(monkeypatch):
    page = FakePage(content_html="", cdp=FakeCdp())
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("ftp://nope", timeout=3, mode="forensic"))

    assert result == {"best": None, "all": [], "timeline": []}
    assert page.goto_calls == []


def test_extraire_flux_cdp_response_captures_m3u8(monkeypatch):
    cdp_params = {
        "requestId": "r1",
        "response": {"url": M3U8_URL, "headers": {"content-type": "application/vnd.apple.mpegurl"}},
    }
    cdp = FakeCdp(events=[("Network.responseReceived", cdp_params)])
    page = FakePage(content_html="<html></html>", cdp=cdp)
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="forensic"))

    assert result["best"] is not None
    assert result["best"]["url"] == M3U8_URL
    types = {entry["type"] for entry in result["all"]}
    assert "cdp_response" in types


def test_extraire_flux_picks_highest_scoring_candidate(monkeypatch):
    """Among competing streams, _score_url's master+/hls weighting elects the richer URL."""
    plain = "https://cdn.example.com/video.m3u8"
    richer = "https://cdn.example.com/hls/master.m3u8"
    cdp = FakeCdp(events=[
        ("Network.responseReceived", {"requestId": "a", "response": {"url": plain, "headers": {}}}),
        ("Network.responseReceived", {"requestId": "b", "response": {"url": richer, "headers": {}}}),
    ])
    page = FakePage(content_html="<html></html>", cdp=cdp)
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="forensic"))

    assert result["best"]["url"] == richer
    urls = {entry["url"] for entry in result["all"]}
    assert urls == {plain, richer}


def test_intercepter_lecteurs_parallele_calls_on_win_with_winning_src(monkeypatch):
    page = FakePage(requests=[FakeRequest(M3U8_URL, {"h": "1"})])
    _patch_interceptor(monkeypatch, FakeBrowser(page))

    wins = []
    result = asyncio.run(
        ic.intercepter_lecteurs_parallele(
            [{"src": "http://host/embed1"}], timeout=2, on_win=wins.append
        )
    )

    assert result == {"url": M3U8_URL, "headers": {"h": "1"}}
    assert wins == ["http://host/embed1"]
