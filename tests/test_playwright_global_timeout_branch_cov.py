import asyncio
import logging

import pytest

import engine.download.extractor.browser_extractor as be
import engine.download.interceptor as ic


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


class _HangingPage:
    def __init__(self):
        self.main_frame = self
        self.url = "http://host/main"
        self.closed = False
        self.goto_calls = []
        self.click_calls = []
        self._handlers = {}

    @property
    def frames(self):
        return [self.main_frame]

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    async def goto(self, *args, **kwargs):
        self.goto_calls.append(kwargs)
        await asyncio.get_running_loop().create_future()

    async def click(self, selector, timeout=None):
        self.click_calls.append((selector, timeout))
        raise RuntimeError("no play button")

    async def content(self):
        return ""

    async def evaluate(self, js):
        return []

    async def close(self):
        self.closed = True


class _Cdp:
    def __init__(self):
        self.detached = False
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    def on(self, event, handler):
        return None

    async def detach(self):
        self.detached = True


class _Ctx:
    def __init__(self, page, cdp):
        self._page = page
        self._cdp = cdp
        self.closed = False
        self.init_scripts = []

    async def new_page(self):
        return self._page

    async def add_init_script(self, js):
        self.init_scripts.append(js)

    async def new_cdp_session(self, page):
        return self._cdp

    async def close(self):
        self.closed = True


class _Browser:
    def __init__(self, page, cdp):
        self._page = page
        self._cdp = cdp
        self.contexts = []

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        ctx = _Ctx(self._page, self._cdp)
        self.contexts.append(ctx)
        return ctx


def _semaphore_fully_released() -> bool:
    async def _probe():
        sem = ic._ctx_semaphore()
        acquired = 0
        for _ in range(ic.MAX_CONTEXTS_SIMULTANES):
            try:
                await asyncio.wait_for(sem.acquire(), timeout=0.05)
                acquired += 1
            except TimeoutError:
                break
        for _ in range(acquired):
            sem.release()
        return acquired

    return asyncio.run(_probe()) == ic.MAX_CONTEXTS_SIMULTANES


def test_extraire_flux_global_deadline_cuts_and_cleans_up(monkeypatch, caplog):
    page = _HangingPage()
    cdp = _Cdp()
    browser = _Browser(page, cdp)

    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "apply_stealth", _anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    monkeypatch.setattr(be.asyncio, "sleep", _anoop)
    monkeypatch.setattr(be, "_deadline_extraction", lambda _t: 0.05)

    with caplog.at_level(logging.WARNING, logger="engine.download.extractor.browser_extractor"):
        result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="standard"))

    assert result == {"best": None, "all": [], "timeline": []}
    assert page.goto_calls
    assert page.closed is True
    assert cdp.detached is True
    assert browser.contexts[0].closed is True
    assert any("deadline globale" in rec.message for rec in caplog.records)
    assert _semaphore_fully_released()


def test_intercepter_lecteur_global_deadline_cuts_and_cleans_up(monkeypatch, caplog):
    page = _HangingPage()
    cdp = _Cdp()
    browser = _Browser(page, cdp)

    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "_get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "_appliquer_stealth", _anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    monkeypatch.setattr(ic.asyncio, "sleep", _anoop)
    monkeypatch.setattr(ic, "_deadline_interception", lambda _t: 0.05)

    with caplog.at_level(logging.WARNING, logger="engine.download.interceptor"):
        result = asyncio.run(ic.intercepter_lecteur("http://host/embed", timeout=2))

    assert result is None
    assert page.goto_calls
    assert page.closed is True
    assert browser.contexts[0].closed is True
    assert any("deadline globale" in rec.message for rec in caplog.records)
    assert _semaphore_fully_released()
