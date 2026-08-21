import asyncio

import pytest

import engine.download._rate_limiter as rl
import engine.download.interceptor as ic
from engine.download._domain_strategy import hote_mort, partition_lecteurs


@pytest.fixture(autouse=True)
def _clean_state():
    with rl._domain_lock:
        rl._host_throttle.clear()
    ic._ctx_semaphore_state["sem"] = None
    ic._ctx_semaphore_state["loop"] = None
    ic._browser_lock_state["lock"] = None
    ic._browser_lock_state["loop"] = None
    yield
    with rl._domain_lock:
        rl._host_throttle.clear()


async def _anoop(*a, **k):
    return None


def test_marquer_et_hote_throttle_expire(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rl.time, "time", lambda: clock[0])

    rl.marquer_hote_throttle("vidmoly.to")
    assert rl.hote_throttle("vidmoly.to") is True

    clock[0] = 1000.0 + rl.domain_penalty("vidmoly.to") + 1.0
    assert rl.hote_throttle("vidmoly.to") is False
    with rl._domain_lock:
        assert "vidmoly.to" not in rl._host_throttle


def test_hote_throttle_empty_and_unknown():
    assert rl.marquer_hote_throttle("") is None
    assert rl.hote_throttle("") is False
    assert rl.hote_throttle("jamais-vu.tld") is False


class _Page:
    def __init__(self, url):
        self.url = url
        self.frames = [self]
        self._handlers = {}
        self.closed = False

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    async def goto(self, *a, **k):
        return None

    async def set_content(self, *a, **k):
        return None

    async def query_selector(self, sel):
        return None

    async def click(self, sel, timeout=None):
        raise RuntimeError("no play button")

    async def close(self):
        self.closed = True


class _Ctx:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page

    async def route(self, *a, **k):
        return None

    async def close(self):
        return None


class _Browser:
    def __init__(self, page):
        self._page = page

    def is_connected(self):
        return True

    async def new_context(self, **k):
        return _Ctx(self._page)


def _patch(monkeypatch, browser):
    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "_get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "_appliquer_stealth", _anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    monkeypatch.setattr(ic.asyncio, "sleep", _anoop)


def test_intercepter_skips_throttled_host_without_browser(monkeypatch):
    async def _boom():
        raise AssertionError("browser must NOT launch for a throttled host")

    monkeypatch.setattr(ic, "_get_browser", _boom)
    with rl._domain_lock:
        rl._host_throttle["vidmoly.to"] = rl.time.time() + 999.0

    res = asyncio.run(ic.intercepter_lecteur("https://vidmoly.to/embed-x.html", timeout=2))
    assert res is None


def test_intercepter_marks_throttle_on_ww_decoy(monkeypatch):
    page = _Page("https://ww547.vidmoly.to/")
    _patch(monkeypatch, _Browser(page))

    res = asyncio.run(ic.intercepter_lecteur("https://vidmoly.to/embed-x.html", timeout=2))

    assert res is None
    assert rl.hote_throttle("vidmoly.to") is True


def test_partition_drops_dead_oneupload():
    assert hote_mort("oneupload.to") is True
    assert hote_mort("cdn.oneupload.to") is True
    assert hote_mort("vidmoly.to") is False

    lecteurs = [
        {"src": "https://oneupload.to/embed-ibs4ry4fldtl.html", "host": "oneupload"},
        {"src": "https://vidmoly.to/embed-xpqa9j589gk0.html", "host": "vidmoly"},
    ]
    ytdlp, autres = partition_lecteurs(lecteurs)
    restants = [l["src"] for l in ytdlp + autres]
    assert not any("oneupload" in s for s in restants)
    assert any("vidmoly" in s for s in restants)
