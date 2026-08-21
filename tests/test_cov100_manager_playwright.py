"""Covers the success + close-error branch of _login_playwright deterministically
with a faked async_playwright (no real Chromium)."""

import asyncio

import playwright.async_api as pw_api

from engine.auth.manager import AuthManager

_COOKIES = [{"name": "remember_token", "value": "323966:hash"}]


class _Page:
    def __init__(self):
        self.fill_calls = []
        self.click_calls = []

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
        return _COOKIES


class _Browser:
    def __init__(self, ctx):
        self._ctx = ctx
        self.close_calls = 0

    async def new_context(self, **kwargs):
        return self._ctx

    async def close(self):
        self.close_calls += 1
        raise RuntimeError("close failed")


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


def test_login_playwright_success_close_error_swallowed(monkeypatch):
    page = _Page()
    browser = _Browser(_Ctx(page))
    monkeypatch.setattr(pw_api, "async_playwright", lambda: _CM(browser))

    result = asyncio.run(AuthManager()._login_playwright("utilisateur_test", "pw"))

    assert result == {"ok": True, "cookies": _COOKIES}
    assert ("#loginPseudo", "utilisateur_test") in page.fill_calls
    assert ("#loginPassword", "pw") in page.fill_calls
    assert page.click_calls == ["#formLogin button[type='submit']"]
    assert browser.close_calls == 1
