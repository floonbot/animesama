import asyncio

import pytest

import engine.download._rate_limiter as rl
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


def _wire(monkeypatch, calls):
    async def fake_ytdlp(lecteurs, *a, **k):
        calls.append(("ytdlp", [l.get("host") for l in lecteurs]))
        return None

    async def fake_extraire(lecteurs, *a, **k):
        calls.append(("sniff", [l.get("host") for l in lecteurs]))
        return None

    monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", fake_ytdlp)
    monkeypatch.setattr(pipeline, "_extraire_et_telecharger", fake_extraire)
    monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
    monkeypatch.setattr(pipeline, "DELAI_RETRY_EFFECTIF", 0)


_YTB = [{"src": "https://vidmoly.net/embed-x.html", "host": "vidmoly"}]
_PWB = [{"src": "https://filemoon.sx/e/y", "host": "filemoon"}]


def test_step_b_sniffs_ytdlp_bucket_when_both_buckets(monkeypatch):
    calls = []
    _wire(monkeypatch, calls)

    fichier, _ = asyncio.run(
        pipeline._cascade_download(list(_YTB), list(_PWB), "/d", "ep", "[x]", FakeQueue())
    )

    assert fichier is None
    assert ("sniff", ["vidmoly"]) in calls


def test_step_b_suppressed_when_ytdlp_host_throttled(monkeypatch):
    calls = []
    _wire(monkeypatch, calls)
    rl.marquer_hote_throttle("vidmoly.net")

    asyncio.run(
        pipeline._cascade_download(list(_YTB), list(_PWB), "/d", "ep", "[x]", FakeQueue())
    )

    assert ("sniff", ["vidmoly"]) not in calls
    assert ("sniff", ["filemoon"]) in calls


def test_step_b_suppressed_when_global_cooldown(monkeypatch):
    calls = []
    _wire(monkeypatch, calls)
    now = rl.time.time()
    with rl._domain_lock:
        rl._recent_bans[:] = [now, now, now, now, now]

    asyncio.run(
        pipeline._cascade_download(list(_YTB), list(_PWB), "/d", "ep", "[x]", FakeQueue())
    )

    assert ("sniff", ["vidmoly"]) not in calls


def test_ytdlp_sur_lecteurs_skips_throttled_host(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)

    async def no_wait(d):
        return None

    monkeypatch.setattr(pipeline, "domain_wait", no_wait)
    monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

    async def boom(fn, *a):
        raise AssertionError("hôte throttlé ne doit pas être re-tenté via yt-dlp")

    monkeypatch.setattr(pipeline, "_run_in_pool", boom)
    rl.marquer_hote_throttle("sendvid.com")

    lec = {"src": "https://sendvid.com/embed/x", "host": "sendvid"}
    res = asyncio.run(pipeline._ytdlp_sur_lecteurs([lec], "/tmp", "ep", "[x]", FakeQueue()))
    assert res is None


def test_single_bucket_ytdlp_only_unchanged(monkeypatch):
    calls = []
    _wire(monkeypatch, calls)

    asyncio.run(
        pipeline._cascade_download(list(_YTB), [], "/d", "ep", "[x]", FakeQueue())
    )

    assert calls == [("ytdlp", ["vidmoly"]), ("sniff", ["vidmoly"])]
