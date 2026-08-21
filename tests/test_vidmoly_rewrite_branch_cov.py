import asyncio

import pytest

from engine.download import _host_breakers as hb
from engine.download import pipeline
from engine.download._domain_strategy import reecrire_domaine, strategie_lecteur
from engine.download.queue import CancelToken


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()

    def emit(self, *a, **k):
        pass


@pytest.fixture(autouse=True)
def _clear_breakers():
    hb._breakers.clear()
    yield
    hb._breakers.clear()


def test_reecrire_domaine_vidmoly_variants_to_net():
    assert reecrire_domaine("https://vidmoly.to/embed-x.html") == "https://vidmoly.net/embed-x.html"
    assert reecrire_domaine("https://vidmoly.me/embed-x.html?a=1") == "https://vidmoly.net/embed-x.html?a=1"
    assert reecrire_domaine("https://vidmoly.biz/embed-x.html") == "https://vidmoly.net/embed-x.html"
    assert reecrire_domaine("https://www.vidmoly.to/embed-x.html") == "https://vidmoly.net/embed-x.html"


def test_reecrire_domaine_passthrough():
    assert reecrire_domaine("https://vidmoly.net/embed-x.html") == "https://vidmoly.net/embed-x.html"
    assert reecrire_domaine("https://video.sibnet.ru/v") == "https://video.sibnet.ru/v"
    assert reecrire_domaine("") == ""
    assert reecrire_domaine("notaurl") == "notaurl"


def test_vidmoly_routes_ytdlp_first():
    assert strategie_lecteur({"src": "https://vidmoly.to/embed-x.html"}) == "ytdlp_first"


def test_ytdlp_sur_lecteurs_rewrites_vidmoly_to_net(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)

    async def no_wait(d):
        return None

    monkeypatch.setattr(pipeline, "domain_wait", no_wait)
    monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

    seen = {}

    async def pool(fn, src, *a):
        seen["src"] = src
        return "out.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    lec = {"src": "https://vidmoly.to/embed-xpqa9j589gk0.html", "host": "vidmoly"}
    res = asyncio.run(pipeline._ytdlp_sur_lecteurs([lec], "/tmp", "ep", "[x]", FakeQueue()))

    assert res == "out.mp4"
    assert seen["src"] == "https://vidmoly.net/embed-xpqa9j589gk0.html"
