import asyncio

import playwright.async_api as pw_api
import pytest

from engine.auth.manager import AuthManager

SUCCESS_COOKIES = [
    {"name": "PHPSESSID", "value": "x"},
    {"name": "remember_token", "value": "323966:hash"},
]
NO_TOKEN_COOKIES = [{"name": "PHPSESSID", "value": "x"}]


class FakePage:
    def __init__(self, *, goto_exc=None, wait_url_exc=None):
        self._goto_exc = goto_exc
        self._wait_url_exc = wait_url_exc
        self.goto_calls = []
        self.wait_for_selector_calls = []
        self.fill_calls = []
        self.click_calls = []
        self.wait_for_url_calls = []

    async def goto(self, *args, **kwargs):
        self.goto_calls.append((args, kwargs))
        if self._goto_exc is not None:
            raise self._goto_exc

    async def wait_for_selector(self, sel, timeout=None):
        self.wait_for_selector_calls.append((sel, timeout))

    async def fill(self, sel, val):
        self.fill_calls.append((sel, val))

    async def click(self, sel):
        self.click_calls.append(sel)

    async def wait_for_url(self, pattern, timeout=None):
        self.wait_for_url_calls.append((pattern, timeout))
        if self._wait_url_exc is not None:
            raise self._wait_url_exc


class FakeContext:
    def __init__(self, *, page, cookies):
        self._page = page
        self._cookies = cookies
        self.new_page_calls = 0
        self.cookies_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        return self._page

    async def cookies(self):
        self.cookies_calls += 1
        return self._cookies


class FakeBrowser:
    def __init__(self, *, ctx):
        self._ctx = ctx
        self.close_calls = 0
        self.new_context_kwargs = None

    async def new_context(self, **kwargs):
        self.new_context_kwargs = kwargs
        return self._ctx

    async def close(self):
        self.close_calls += 1


class FakeChromium:
    def __init__(self, *, browser):
        self._browser = browser
        self.launch_kwargs = None

    async def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self._browser


class FakePlaywright:
    def __init__(self, *, browser):
        self.chromium = FakeChromium(browser=browser)


class FakeAsyncPlaywrightCM:
    def __init__(self, *, browser):
        self._browser = browser

    async def __aenter__(self):
        return FakePlaywright(browser=self._browser)

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _build(*, goto_exc=None, wait_url_exc=None, cookies=SUCCESS_COOKIES):
    page = FakePage(goto_exc=goto_exc, wait_url_exc=wait_url_exc)
    ctx = FakeContext(page=page, cookies=cookies)
    browser = FakeBrowser(ctx=ctx)
    cm = FakeAsyncPlaywrightCM(browser=browser)
    return page, ctx, browser, cm, (lambda: cm)


@pytest.fixture
def patch_pw(monkeypatch):
    def _apply(factory):
        monkeypatch.setattr(pw_api, "async_playwright", factory)
    return _apply


def test_success_returns_cookies_and_closes(patch_pw):
    page, ctx, browser, cm, factory = _build()
    patch_pw(factory)

    result = asyncio.run(AuthManager()._login_playwright("utilisateur_test", "pw"))

    assert result == {"ok": True, "cookies": SUCCESS_COOKIES}
    assert browser.close_calls == 1
    assert ctx.cookies_calls == 1


def test_success_fills_pseudo_and_password(patch_pw):
    page, ctx, browser, cm, factory = _build()
    patch_pw(factory)

    asyncio.run(AuthManager()._login_playwright("utilisateur_test", "secret"))

    filled = dict(page.fill_calls)
    assert filled["#loginPseudo"] == "utilisateur_test"
    assert filled["#loginPassword"] == "secret"
    assert page.click_calls == ["#formLogin button[type='submit']"]


def test_no_remember_token_is_failure(patch_pw):
    page, ctx, browser, cm, factory = _build(cookies=NO_TOKEN_COOKIES)
    patch_pw(factory)

    result = asyncio.run(AuthManager()._login_playwright("utilisateur_test", "pw"))

    assert result == {"ok": False, "message": "Identifiants incorrects"}
    assert browser.close_calls == 1


def test_exception_during_goto_caught_and_closes(patch_pw):
    page, ctx, browser, cm, factory = _build(goto_exc=Exception("boom"))
    patch_pw(factory)

    result = asyncio.run(AuthManager()._login_playwright("utilisateur_test", "pw"))

    assert result == {
        "ok": False,
        "message": "Erreur de connexion — vérifie tes identifiants",
    }
    assert browser.close_calls == 1
    assert ctx.cookies_calls == 0


def test_timeout_on_wait_for_url_swallowed_reaches_success(patch_pw):
    page, ctx, browser, cm, factory = _build(wait_url_exc=pw_api.TimeoutError("slow"))
    patch_pw(factory)

    result = asyncio.run(AuthManager()._login_playwright("utilisateur_test", "pw"))

    assert result == {"ok": True, "cookies": SUCCESS_COOKIES}
    assert page.wait_for_url_calls == [("**/profil**", 15_000)]
    assert browser.close_calls == 1
