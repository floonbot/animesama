import asyncio

from engine.download import pipeline
from engine.download.queue import CancelToken


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


class FakeBreaker:
    async def call(self, fn, *args):
        return await fn(*args)


LECTEUR = {"src": "https://player.example/embed", "host": "player.example"}


class TestYtdlpSurLecteursSsrf:
    def test_unsafe_url_is_skipped_and_no_download(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: False)
        called = []

        async def must_not_pool(*a, **k):
            called.append(a)
            return "should-not-happen"

        monkeypatch.setattr(pipeline, "_run_in_pool", must_not_pool)
        q = FakeQueue()
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q, referer="r")
        )
        assert out is None
        assert called == []

    def test_safe_url_runs_engine_and_returns_file(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)

        async def no_wait(domain):
            return None

        monkeypatch.setattr(pipeline, "domain_wait", no_wait)
        monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

        async def pool(fn, *a):
            return "out.mp4"

        monkeypatch.setattr(pipeline, "_run_in_pool", pool)
        q = FakeQueue()
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q, referer="r")
        )
        assert out == "out.mp4"


class TestPipelinePlaywrightImplSsrf:
    def test_all_unsafe_returns_none_without_interception(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: False)

        async def must_not_run(*a, **k):
            raise AssertionError("interception must not run when all players are unsafe")

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteurs_parallele", must_not_run
        )
        q = FakeQueue()
        out = asyncio.run(pipeline._pipeline_playwright_impl([LECTEUR], "[x]", q))
        assert out is None


def _patch_safe(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
    monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)
    monkeypatch.setattr(pipeline, "get_breaker", lambda h: FakeBreaker())


class TestPipelinePlaywrightImplOrder:
    def test_parallel_interception_wins_first(self, monkeypatch):
        _patch_safe(monkeypatch)

        async def parallele(lecteurs, timeout=0, on_win=None):
            return {"url": "https://cdn/parallel.m3u8"}

        async def seq(*a, **k):
            raise AssertionError("sequential interception must not run when parallel succeeds")

        async def extr(*a, **k):
            raise AssertionError("browser extractor must not run when parallel succeeds")

        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteurs_parallele", parallele)
        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteur", seq)
        monkeypatch.setattr("engine.download.extractor.browser_extractor.extraire_flux", extr)
        q = FakeQueue()
        out = asyncio.run(pipeline._pipeline_playwright_impl([LECTEUR], "[x]", q))
        assert out == {"url": "https://cdn/parallel.m3u8"}

    def test_sequential_interception_used_when_parallel_empty(self, monkeypatch):
        _patch_safe(monkeypatch)

        async def parallele(lecteurs, timeout=0, on_win=None):
            return None

        async def seq(src, timeout):
            return {"url": "https://cdn/seq.m3u8"}

        async def extr(*a, **k):
            raise AssertionError("browser extractor must not run when sequential succeeds")

        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteurs_parallele", parallele)
        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteur", seq)
        monkeypatch.setattr("engine.download.extractor.browser_extractor.extraire_flux", extr)
        q = FakeQueue()
        out = asyncio.run(pipeline._pipeline_playwright_impl([LECTEUR], "[x]", q))
        assert out == {"url": "https://cdn/seq.m3u8"}

    def test_browser_extractor_is_last_resort(self, monkeypatch):
        _patch_safe(monkeypatch)

        async def parallele(lecteurs, timeout=0, on_win=None):
            return None

        async def seq(src, timeout):
            return None

        async def extr(src, timeout=0, mode="standard"):
            return {"best": {"url": "https://cdn/forensic.m3u8", "headers": {"r": "1"}}}

        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteurs_parallele", parallele)
        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteur", seq)
        monkeypatch.setattr("engine.download.extractor.browser_extractor.extraire_flux", extr)
        q = FakeQueue()
        out = asyncio.run(pipeline._pipeline_playwright_impl([LECTEUR], "[x]", q))
        assert out == {"url": "https://cdn/forensic.m3u8", "headers": {"r": "1"}}

    def test_all_stages_fail_returns_none(self, monkeypatch):
        _patch_safe(monkeypatch)

        async def parallele(lecteurs, timeout=0, on_win=None):
            return None

        async def seq(src, timeout):
            return None

        async def extr(src, timeout=0, mode="standard"):
            return {}

        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteurs_parallele", parallele)
        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteur", seq)
        monkeypatch.setattr("engine.download.extractor.browser_extractor.extraire_flux", extr)
        q = FakeQueue()
        out = asyncio.run(pipeline._pipeline_playwright_impl([LECTEUR], "[x]", q))
        assert out is None
