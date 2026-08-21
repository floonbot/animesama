import asyncio

import pytest

from engine.download import _host_breakers as hb
from engine.download import pipeline
from engine.download.queue import CancelToken
from engine.observability.metrics import metrics


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


@pytest.fixture(autouse=True)
def _clear_breakers():
    hb._breakers.clear()
    yield
    hb._breakers.clear()


def _patch_common(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)

    async def no_wait(domain):
        return None

    monkeypatch.setattr(pipeline, "domain_wait", no_wait)
    monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)


def test_ytdlp_direct_records_per_host_success(monkeypatch):
    _patch_common(monkeypatch)

    async def pool(fn, *a):
        return "out.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    snap0 = metrics.snapshot()
    a0 = snap0.get("host_attempt_video.sibnet.ru", 0)
    o0 = snap0.get("host_ok_video.sibnet.ru", 0)
    v0 = snap0.get("extract_via_ytdlp_direct", 0)

    lec = {"src": "https://video.sibnet.ru/v", "host": "video.sibnet.ru"}
    out = asyncio.run(
        pipeline._ytdlp_sur_lecteurs([lec], "/tmp", "ep", "[x]", FakeQueue(), referer="r")
    )

    assert out == "out.mp4"
    snap = metrics.snapshot()
    assert snap.get("host_attempt_video.sibnet.ru", 0) == a0 + 1
    assert snap.get("host_ok_video.sibnet.ru", 0) == o0 + 1
    assert snap.get("extract_via_ytdlp_direct", 0) == v0 + 1


def test_fallback_chain_forensic_wins_and_is_logged(monkeypatch):
    """Bascule de repli : interception parallele + sequentielle echouent,
    l'extraction forensic du navigateur reussit, et le maillon gagnant est logge."""
    _patch_common(monkeypatch)

    async def par_none(lecteurs, timeout=8, on_win=None):
        return None

    async def seq_none(src, timeout):
        return None

    async def fake_forensic(src, timeout=10, mode="standard"):
        return {"best": {"url": "https://cdn.example/stream.mp4", "headers": {"referer": "r"}}}

    monkeypatch.setattr(
        "engine.download.interceptor.intercepter_lecteurs_parallele", par_none
    )
    monkeypatch.setattr("engine.download.interceptor.intercepter_lecteur", seq_none)
    monkeypatch.setattr(
        "engine.download.extractor.browser_extractor.extraire_flux", fake_forensic
    )

    snap0 = metrics.snapshot()
    fwd0 = snap0.get("extract_via_browser_forensic", 0)
    ok0 = snap0.get("host_ok_vudeo.io", 0)

    lec = {"src": "https://vudeo.io/embed-x.html", "host": "vudeo.io"}
    result = asyncio.run(pipeline._pipeline_playwright_impl([lec], "[x]", FakeQueue()))

    assert result == {"url": "https://cdn.example/stream.mp4", "headers": {"referer": "r"}}
    snap = metrics.snapshot()
    assert snap.get("extract_via_browser_forensic", 0) == fwd0 + 1
    assert snap.get("host_ok_vudeo.io", 0) == ok0 + 1


def test_unknown_host_forensic_sniff_is_captured_end_to_end(monkeypatch):
    """Filet inconnu (DoD#4) : un hote HORS registre dont le flux n'apparait
    qu'au sniff forensic est quand meme capture et loggue de bout en bout."""
    _patch_common(monkeypatch)

    from engine.download.extractor.registry import get_extractor
    assert get_extractor("weird.unknown.tld").name == "generic"

    async def par_none(lecteurs, timeout=8, on_win=None):
        return None

    async def seq_none(src, timeout):
        return None

    async def fake_forensic(src, timeout=10, mode="standard"):
        return {"best": {"url": "https://cdn.unknown.tld/master.m3u8", "headers": {}}}

    monkeypatch.setattr(
        "engine.download.interceptor.intercepter_lecteurs_parallele", par_none
    )
    monkeypatch.setattr("engine.download.interceptor.intercepter_lecteur", seq_none)
    monkeypatch.setattr(
        "engine.download.extractor.browser_extractor.extraire_flux", fake_forensic
    )

    snap0 = metrics.snapshot()
    fwd0 = snap0.get("extract_via_browser_forensic", 0)
    ok0 = snap0.get("host_ok_weird.unknown.tld", 0)

    lec = {"src": "https://weird.unknown.tld/embed/xyz", "host": "weird.unknown.tld"}
    result = asyncio.run(pipeline._pipeline_playwright_impl([lec], "[x]", FakeQueue()))

    assert result == {"url": "https://cdn.unknown.tld/master.m3u8", "headers": {}}
    snap = metrics.snapshot()
    assert snap.get("extract_via_browser_forensic", 0) == fwd0 + 1
    assert snap.get("host_ok_weird.unknown.tld", 0) == ok0 + 1


def test_parallel_win_is_attributed_to_winning_host(monkeypatch):
    """Le maillon parallele attribue le succes a l'hote du src gagnant (cle 'src' du resultat)."""
    _patch_common(monkeypatch)

    async def par_win(lecteurs, timeout=8, on_win=None):
        if on_win is not None:
            on_win("https://vudeo.io/e2")
        return {"url": "https://cdn/x.m3u8", "headers": {}}

    monkeypatch.setattr(
        "engine.download.interceptor.intercepter_lecteurs_parallele", par_win
    )

    snap0 = metrics.snapshot()
    par0 = snap0.get("extract_via_network_parallel", 0)
    att0 = snap0.get("host_attempt_vudeo.io", 0)
    ok0 = snap0.get("host_ok_vudeo.io", 0)

    lecteurs = [
        {"src": "https://vudeo.io/e1", "host": "vudeo.io"},
        {"src": "https://vudeo.io/e2", "host": "vudeo.io"},
    ]
    result = asyncio.run(pipeline._pipeline_playwright_impl(lecteurs, "[x]", FakeQueue()))

    assert result == {"url": "https://cdn/x.m3u8", "headers": {}}
    snap = metrics.snapshot()
    assert snap.get("extract_via_network_parallel", 0) == par0 + 1
    assert snap.get("host_attempt_vudeo.io", 0) == att0 + 1
    assert snap.get("host_ok_vudeo.io", 0) == ok0 + 1
