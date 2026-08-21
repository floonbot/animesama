import asyncio

import pytest

from engine.download import _host_breakers, pipeline
from engine.download.queue import CancelToken


@pytest.fixture(autouse=True)
def _reset_pipeline_globals():
    saved_cache = dict(pipeline._ext_cache)
    saved_inflight = dict(pipeline._ext_inflight)
    saved_prefetch = pipeline._PREFETCH_ENABLED
    saved_breakers = dict(_host_breakers._breakers)
    pipeline._ext_cache.clear()
    pipeline._ext_inflight.clear()
    _host_breakers._breakers.clear()
    yield
    pipeline._ext_cache.clear()
    pipeline._ext_cache.update(saved_cache)
    pipeline._ext_inflight.clear()
    pipeline._ext_inflight.update(saved_inflight)
    pipeline._PREFETCH_ENABLED = saved_prefetch
    _host_breakers._breakers.clear()
    _host_breakers._breakers.update(saved_breakers)


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


class OpenBreaker:
    def __init__(self, host):
        self.host = host
        self.calls = 0

    async def call(self, fn, *args):
        self.calls += 1
        raise RuntimeError(f"Circuit OUVERT pour '{self.host}'. Réessai dans 7s")


class RaisingBreaker:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    async def call(self, fn, *args):
        self.calls += 1
        raise self.exc


class ForwardBreaker:
    def __init__(self):
        self.calls = 0

    async def call(self, fn, *args):
        self.calls += 1
        return await fn(*args)


def _two_lecteurs():
    return [
        {"src": "https://a.example/embed", "host": "a.example"},
        {"src": "https://b.example/embed", "host": "b.example"},
    ]


def _patch_all_safe(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)


def _no_parallel(monkeypatch):
    async def parallele(lecteurs, timeout=0, on_win=None):
        return None

    monkeypatch.setattr(
        "engine.download.interceptor.intercepter_lecteurs_parallele", parallele
    )


class TestSequentialStageCircuitOpen:
    def test_circuit_open_runtimeerror_is_swallowed_then_extractor_runs(self, monkeypatch):
        _patch_all_safe(monkeypatch)
        _no_parallel(monkeypatch)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)
        breakers = {}

        def make(host):
            b = breakers.get(host)
            if b is None:
                b = OpenBreaker(host)
                breakers[host] = b
            return b

        monkeypatch.setattr(pipeline, "get_breaker", make)

        seq_calls = []

        async def seq(src, timeout):
            seq_calls.append(src)
            return {"url": "should-not-be-reached"}

        monkeypatch.setattr("engine.download.interceptor.intercepter_lecteur", seq)

        extractor_hosts = []

        async def extr(src, timeout=0, mode="standard"):
            extractor_hosts.append(src)
            return {"best": {"url": "https://cdn/forensic.m3u8", "headers": {"x": "1"}}}

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", extr
        )

        q = FakeQueue()
        out = asyncio.run(
            pipeline._pipeline_playwright_impl(_two_lecteurs(), "[x]", q)
        )

        assert out == {"url": "https://cdn/forensic.m3u8", "headers": {"x": "1"}}
        assert breakers["a.example"].calls == 1
        assert breakers["b.example"].calls == 1
        assert seq_calls == []
        assert extractor_hosts == ["https://a.example/embed"]


class TestSequentialStageNonCircuitErrors:
    def test_non_circuit_runtimeerror_swallowed_and_loop_continues(self, monkeypatch):
        _patch_all_safe(monkeypatch)
        _no_parallel(monkeypatch)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)

        first = RaisingBreaker(RuntimeError("aucun flux livré"))
        second = ForwardBreaker()
        seq = iter([first, second])
        monkeypatch.setattr(pipeline, "get_breaker", lambda h: next(seq))

        async def intercept(src, timeout):
            return {"url": "https://cdn/second.m3u8"}

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteur", intercept
        )

        async def extr(*a, **k):
            raise AssertionError("extractor must not run when sequential succeeds")

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", extr
        )

        q = FakeQueue()
        out = asyncio.run(
            pipeline._pipeline_playwright_impl(_two_lecteurs(), "[x]", q)
        )

        assert out == {"url": "https://cdn/second.m3u8"}
        assert first.calls == 1
        assert second.calls == 1

    def test_generic_exception_swallowed_and_loop_continues(self, monkeypatch):
        _patch_all_safe(monkeypatch)
        _no_parallel(monkeypatch)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)

        first = RaisingBreaker(ValueError("boom"))
        second = ForwardBreaker()
        seq = iter([first, second])
        monkeypatch.setattr(pipeline, "get_breaker", lambda h: next(seq))

        async def intercept(src, timeout):
            return {"url": "https://cdn/recovered.m3u8"}

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteur", intercept
        )

        async def extr(*a, **k):
            raise AssertionError("extractor must not run when sequential succeeds")

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", extr
        )

        q = FakeQueue()
        out = asyncio.run(
            pipeline._pipeline_playwright_impl(_two_lecteurs(), "[x]", q)
        )

        assert out == {"url": "https://cdn/recovered.m3u8"}
        assert first.calls == 1
        assert second.calls == 1


class TestSequentialStageHostUnavailable:
    def test_unavailable_host_is_skipped_breaker_not_called(self, monkeypatch):
        _patch_all_safe(monkeypatch)
        _no_parallel(monkeypatch)
        monkeypatch.setattr(
            pipeline, "host_disponible", lambda h: h == "b.example"
        )

        used = ForwardBreaker()
        seen_hosts = []

        def make(host):
            seen_hosts.append(host)
            return used

        monkeypatch.setattr(pipeline, "get_breaker", make)

        intercept_srcs = []

        async def intercept(src, timeout):
            intercept_srcs.append(src)
            return {"url": "https://cdn/b.m3u8"}

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteur", intercept
        )

        async def extr(*a, **k):
            raise AssertionError("extractor must not run")

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", extr
        )

        q = FakeQueue()
        out = asyncio.run(
            pipeline._pipeline_playwright_impl(_two_lecteurs(), "[x]", q)
        )

        assert out == {"url": "https://cdn/b.m3u8"}
        assert seen_hosts == ["b.example"]
        assert intercept_srcs == ["https://b.example/embed"]
        seq_lines = [
            d["line"]
            for ev, d in q.events
            if ev == "episode_progress" and d["line"].startswith("Recherche de la vidéo")
        ]
        assert seq_lines == ["Recherche de la vidéo 2/2 (b.example)…"]


class TestSequentialStageCancelled:
    def test_cancellation_breaks_sequential_loop_then_extractor_loop(self, monkeypatch):
        _patch_all_safe(monkeypatch)
        _no_parallel(monkeypatch)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)

        breaker_calls = []

        def make(host):
            breaker_calls.append(host)
            return ForwardBreaker()

        monkeypatch.setattr(pipeline, "get_breaker", make)

        async def intercept(src, timeout):
            raise AssertionError("interception must not run after cancellation")

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteur", intercept
        )

        async def extr(*a, **k):
            raise AssertionError("extractor must not run after cancellation")

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", extr
        )

        q = FakeQueue()
        q._cancelled.set()
        out = asyncio.run(
            pipeline._pipeline_playwright_impl(_two_lecteurs(), "[x]", q)
        )

        assert out is None
        assert breaker_calls == []


class TestBrowserExtractorFallback:
    def test_no_best_for_all_returns_none(self, monkeypatch):
        _patch_all_safe(monkeypatch)
        _no_parallel(monkeypatch)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)
        monkeypatch.setattr(pipeline, "get_breaker", lambda h: ForwardBreaker())

        async def intercept(src, timeout):
            return None

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteur", intercept
        )

        extr_srcs = []

        async def extr(src, timeout=0, mode="standard"):
            extr_srcs.append(src)
            return {"best": None}

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", extr
        )

        q = FakeQueue()
        out = asyncio.run(
            pipeline._pipeline_playwright_impl(_two_lecteurs(), "[x]", q)
        )

        assert out is None
        assert extr_srcs == [
            "https://a.example/embed",
            "https://b.example/embed",
        ]

    def test_extractor_raises_is_swallowed_then_next_succeeds(self, monkeypatch):
        _patch_all_safe(monkeypatch)
        _no_parallel(monkeypatch)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)
        monkeypatch.setattr(pipeline, "get_breaker", lambda h: ForwardBreaker())

        async def intercept(src, timeout):
            return None

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteur", intercept
        )

        calls = []

        async def extr(src, timeout=0, mode="standard"):
            calls.append(src)
            if src == "https://a.example/embed":
                raise RuntimeError("extractor blew up")
            return {"best": {"url": "https://cdn/from_b.m3u8"}}

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", extr
        )

        q = FakeQueue()
        out = asyncio.run(
            pipeline._pipeline_playwright_impl(_two_lecteurs(), "[x]", q)
        )

        assert out == {"url": "https://cdn/from_b.m3u8", "headers": {}}
        assert calls == [
            "https://a.example/embed",
            "https://b.example/embed",
        ]

    def test_extractor_raises_for_all_returns_none(self, monkeypatch):
        _patch_all_safe(monkeypatch)
        _no_parallel(monkeypatch)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)
        monkeypatch.setattr(pipeline, "get_breaker", lambda h: ForwardBreaker())

        async def intercept(src, timeout):
            return None

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteur", intercept
        )

        calls = []

        async def extr(src, timeout=0, mode="standard"):
            calls.append(src)
            raise RuntimeError("always fails")

        monkeypatch.setattr(
            "engine.download.extractor.browser_extractor.extraire_flux", extr
        )

        q = FakeQueue()
        out = asyncio.run(
            pipeline._pipeline_playwright_impl(_two_lecteurs(), "[x]", q)
        )

        assert out is None
        assert calls == [
            "https://a.example/embed",
            "https://b.example/embed",
        ]


class TestPrefetchSuccess:
    def test_success_writes_to_ext_cache(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

        async def no_sleep(_):
            return None

        monkeypatch.setattr(pipeline.asyncio, "sleep", no_sleep)

        async def lecteurs(url):
            return [{"src": "https://p.example/embed", "host": "p.example"}]

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", lecteurs)
        monkeypatch.setattr(
            pipeline, "partition_lecteurs", lambda lec: ([], list(lec))
        )

        captured = {}

        async def fake_pipeline(playwright_lecteurs, ep_label, queue):
            captured["label"] = ep_label
            captured["queue_type"] = type(queue).__name__
            return {"url": "https://cdn/prefetched.m3u8", "headers": {"r": "1"}}

        monkeypatch.setattr(pipeline, "_pipeline_playwright", fake_pipeline)

        ep = {"url": "https://anime-sama.to/ep?ep=3"}
        q = FakeQueue()
        asyncio.run(pipeline.prefetch_extraction(ep, q))

        assert ep["url"] in pipeline._ext_cache
        _ts, stored = pipeline._ext_cache[ep["url"]]
        assert stored == {"url": "https://cdn/prefetched.m3u8", "headers": {"r": "1"}}
        assert captured["label"] == "prefetch"
        assert captured["queue_type"] == "_SilentQueue"
        assert ep["url"] not in pipeline._ext_inflight

    def test_ytdlp_present_skips_playwright_and_no_cache(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

        async def no_sleep(_):
            return None

        monkeypatch.setattr(pipeline.asyncio, "sleep", no_sleep)

        async def lecteurs(url):
            return [{"src": "https://y.example/embed", "host": "y.example"}]

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", lecteurs)
        monkeypatch.setattr(
            pipeline, "partition_lecteurs", lambda lec: (list(lec), [])
        )

        async def must_not_run(*a, **k):
            raise AssertionError("playwright pipeline must not run when ytdlp present")

        monkeypatch.setattr(pipeline, "_pipeline_playwright", must_not_run)

        ep = {"url": "https://anime-sama.to/ep?ep=4"}
        q = FakeQueue()
        asyncio.run(pipeline.prefetch_extraction(ep, q))

        assert ep["url"] not in pipeline._ext_cache
        assert ep["url"] not in pipeline._ext_inflight


class TestPrefetchCancelled:
    def test_cancel_after_sleep_returns_before_get_lecteurs(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        q = FakeQueue()

        async def cancel_then_sleep(_):
            q._cancelled.set()
            return None

        monkeypatch.setattr(pipeline.asyncio, "sleep", cancel_then_sleep)

        async def must_not_run(url):
            raise AssertionError("get_lecteurs_async must not run after cancellation")

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", must_not_run)

        ep = {"url": "https://anime-sama.to/ep?ep=5"}
        asyncio.run(pipeline.prefetch_extraction(ep, q))

        assert ep["url"] not in pipeline._ext_cache
        assert ep["url"] not in pipeline._ext_inflight

    def test_cancel_after_get_lecteurs_returns_before_pipeline(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

        async def no_sleep(_):
            return None

        monkeypatch.setattr(pipeline.asyncio, "sleep", no_sleep)
        q = FakeQueue()

        async def lecteurs(url):
            q._cancelled.set()
            return [{"src": "https://p.example/embed", "host": "p.example"}]

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", lecteurs)

        def must_not_partition(lec):
            raise AssertionError("partition must not run after cancellation")

        monkeypatch.setattr(pipeline, "partition_lecteurs", must_not_partition)

        async def must_not_pipeline(*a, **k):
            raise AssertionError("pipeline must not run after cancellation")

        monkeypatch.setattr(pipeline, "_pipeline_playwright", must_not_pipeline)

        ep = {"url": "https://anime-sama.to/ep?ep=6"}
        asyncio.run(pipeline.prefetch_extraction(ep, q))

        assert ep["url"] not in pipeline._ext_cache
        assert ep["url"] not in pipeline._ext_inflight

    def test_cancel_after_pipeline_skips_cache_write(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

        async def no_sleep(_):
            return None

        monkeypatch.setattr(pipeline.asyncio, "sleep", no_sleep)
        q = FakeQueue()

        async def lecteurs(url):
            return [{"src": "https://p.example/embed", "host": "p.example"}]

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", lecteurs)
        monkeypatch.setattr(
            pipeline, "partition_lecteurs", lambda lec: ([], list(lec))
        )

        async def fake_pipeline(playwright_lecteurs, ep_label, queue):
            q._cancelled.set()
            return {"url": "https://cdn/late.m3u8"}

        monkeypatch.setattr(pipeline, "_pipeline_playwright", fake_pipeline)

        ep = {"url": "https://anime-sama.to/ep?ep=7"}
        asyncio.run(pipeline.prefetch_extraction(ep, q))

        assert ep["url"] not in pipeline._ext_cache
        assert ep["url"] not in pipeline._ext_inflight
