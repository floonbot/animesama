import asyncio

import pytest

from engine.download import _host_breakers as hb
from engine.download import pipeline
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


def _patch(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)

    async def no_wait(d):
        return None

    monkeypatch.setattr(pipeline, "domain_wait", no_wait)
    monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)


def test_ytdlp_saute_hote_non_gere_par_ytdlp(monkeypatch):
    _patch(monkeypatch)

    async def boom(fn, *a):
        raise AssertionError("yt-dlp ne doit pas être tenté sur un hôte sniff-only")

    monkeypatch.setattr(pipeline, "_run_in_pool", boom)

    lec = {"src": "https://vudeo.io/embed-x.html", "host": "vudeo.io"}
    res = asyncio.run(pipeline._ytdlp_sur_lecteurs([lec], "/tmp", "ep", "[x]", FakeQueue()))
    assert res is None


def test_ytdlp_tente_bien_un_hote_generique(monkeypatch):
    _patch(monkeypatch)
    called = []

    async def pool(fn, *a):
        called.append(True)
        return "out.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    lec = {"src": "https://player.example/embed", "host": "player.example"}
    res = asyncio.run(pipeline._ytdlp_sur_lecteurs([lec], "/tmp", "ep", "[x]", FakeQueue()))
    assert res == "out.mp4"
    assert called
