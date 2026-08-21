import asyncio

import pytest

import engine.download.interceptor as interceptor


class _FauxNavigateur:
    def is_connected(self):
        return True

    async def close(self):
        pass


class _FauxChromium:
    def __init__(self, vus):
        self._vus = vus

    async def launch(self, **kwargs):
        self._vus.append(kwargs)
        return _FauxNavigateur()


class _FauxPlaywright:
    def __init__(self, vus):
        self.chromium = _FauxChromium(vus)

    async def stop(self):
        pass


class _FauxDemarreur:
    def __init__(self, vus):
        self._vus = vus

    async def start(self):
        return _FauxPlaywright(self._vus)


@pytest.fixture
def args_de_lancement(monkeypatch):
    vus: list[dict] = []
    monkeypatch.setattr(interceptor, "_browser", None)
    monkeypatch.setattr(interceptor, "_playwright", None)

    import playwright.async_api as pw_api

    monkeypatch.setattr(pw_api, "async_playwright", lambda: _FauxDemarreur(vus))

    asyncio.run(interceptor._get_browser())
    interceptor._browser = None
    interceptor._playwright = None

    assert vus, "chromium.launch n'a pas ete appele"
    return vus[0].get("args", [])


def test_chromium_ne_desactive_pas_le_bac_a_sable(args_de_lancement):
    assert "--no-sandbox" not in args_de_lancement


def test_disable_dev_shm_usage_conserve(args_de_lancement):
    assert "--disable-dev-shm-usage" in args_de_lancement
