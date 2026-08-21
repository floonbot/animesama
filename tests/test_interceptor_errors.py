import asyncio

import pytest

import engine.download.interceptor as ic


async def _anoop(*args, **kwargs):
    return None


class FakeCtx:
    def __init__(self, page):
        self._page = page
        self.closed = False

    async def new_page(self):
        return self._page

    async def close(self):
        self.closed = True


class FakePage:
    def __init__(self, goto_exc=None, click_exc=None):
        self._goto_exc = goto_exc
        self._click_exc = click_exc
        self._handlers = {}
        self.closed = False
        self.goto_calls = []
        self.click_calls = []
        self.url = "https://fake.local/"
        self.frames = [self]

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    async def goto(self, *args, **kwargs):
        self.goto_calls.append(kwargs)
        if self._goto_exc is not None:
            raise self._goto_exc
        for handler in self._handlers.get("request", []):
            for req in []:
                handler(req)

    async def query_selector(self, selector):
        return object()

    async def click(self, selector, timeout=None):
        self.click_calls.append((selector, timeout))
        if self._click_exc is not None:
            raise self._click_exc(selector)

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page, new_context_exc=None):
        self._page = page
        self._new_context_exc = new_context_exc
        self.contexts = []

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        if self._new_context_exc is not None:
            raise self._new_context_exc
        ctx = FakeCtx(self._page)
        self.contexts.append(ctx)
        return ctx


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
    monkeypatch.setattr(ic.asyncio, "sleep", _anoop)


def test_goto_raises_is_caught_returns_none(monkeypatch):
    page = FakePage(goto_exc=Exception("boom"))
    browser = FakeBrowser(page)
    _patch_interceptor(monkeypatch, browser)

    reset_calls = []

    async def _recorder():
        reset_calls.append(True)

    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _recorder)

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result is None
    assert page.goto_calls != []
    assert page.click_calls != []
    assert reset_calls == []
    assert page.closed is True


def test_erreur_grave_triggers_reset_and_returns_none(monkeypatch):
    page = FakePage()
    browser = FakeBrowser(page, new_context_exc=Exception("ctx-explode"))
    _patch_interceptor(monkeypatch, browser)

    reset_calls = []

    async def _recorder():
        reset_calls.append(True)

    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _recorder)

    result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result is None
    assert reset_calls == [True]
    assert browser.contexts == []


def test_tenter_clic_play_first_selector_succeeds(monkeypatch):
    page = FakePage()

    asyncio.run(ic._tenter_clic_play(page))

    assert len(page.click_calls) == 1
    assert page.click_calls[0][0] == ic.PLAY_SELECTORS[0]


def test_tenter_clic_play_closed_target_returns_early(monkeypatch):
    from playwright.async_api import Error as PWError

    def _raise(selector):
        raise PWError("Target closed")

    page = FakePage(click_exc=_raise)

    asyncio.run(ic._tenter_clic_play(page))

    assert len(page.click_calls) == 1
    assert page.click_calls[0][0] == ic.PLAY_SELECTORS[0]


def test_tenter_clic_play_generic_exception_tries_all_selectors(monkeypatch):
    def _raise(selector):
        raise Exception("no such element")

    page = FakePage(click_exc=_raise)

    asyncio.run(ic._tenter_clic_play(page))

    assert len(page.click_calls) == len(ic.PLAY_SELECTORS)
    attempted = [call[0] for call in page.click_calls]
    assert attempted == list(ic.PLAY_SELECTORS)


class _PrefilterFrame:
    def __init__(self, present):
        self.present = set(present)
        self.qs = []
        self.click_calls = []
        self.url = "https://fake.local/"

    async def query_selector(self, selector):
        self.qs.append(selector)
        return object() if selector in self.present else None

    async def click(self, selector, timeout=None):
        self.click_calls.append((selector, timeout))


class _PrefilterPage:
    def __init__(self, frame):
        self.frames = [frame]


def test_tenter_clic_play_prefilter_skips_absent_selectors():
    frame = _PrefilterFrame(present=[])
    asyncio.run(ic._tenter_clic_play(_PrefilterPage(frame)))
    assert frame.click_calls == []
    assert len(frame.qs) == len(ic.PLAY_SELECTORS)


def test_tenter_clic_play_prefilter_clicks_only_present_selector():
    target = ic.PLAY_SELECTORS[2]
    frame = _PrefilterFrame(present=[target])
    asyncio.run(ic._tenter_clic_play(_PrefilterPage(frame)))
    assert [c[0] for c in frame.click_calls] == [target]
