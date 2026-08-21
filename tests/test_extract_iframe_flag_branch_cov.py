import asyncio

import engine.download.interceptor as ic


class _FakeEmbedPage:
    def __init__(self):
        self.goto_calls = []
        self.content = None

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    async def set_content(self, html, **kwargs):
        self.content = html


def test_charger_embed_goto_direct_quand_flag_off(monkeypatch):
    monkeypatch.delenv("DL_EXTRACT_IFRAME", raising=False)
    page = _FakeEmbedPage()
    asyncio.run(ic._charger_embed(page, "https://vidmoly.to/embed-x", "https://site"))
    assert page.goto_calls == ["https://vidmoly.to/embed-x"]
    assert page.content is None


def test_charger_embed_iframe_sandbox_quand_flag_on(monkeypatch):
    monkeypatch.setenv("DL_EXTRACT_IFRAME", "1")
    page = _FakeEmbedPage()
    asyncio.run(ic._charger_embed(page, "https://vidmoly.to/embed-x", "https://site"))

    assert page.goto_calls == ["https://site/"]
    assert page.content is not None
    assert 'sandbox="allow-scripts allow-same-origin' in page.content
    assert "allow-top-navigation" not in page.content
    assert "allow-popups" not in page.content
    assert "https://vidmoly.to/embed-x" in page.content
