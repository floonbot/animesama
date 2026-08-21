import asyncio
from types import SimpleNamespace

import pytest

from engine.domain.exceptions import DownloadCancelled
from engine.download import _domain_strategy as ds
from engine.download import _rate_limiter as rl
from engine.download import _runtime as runtime
from engine.download import pipeline
from engine.download.queue import CancelToken


@pytest.fixture(autouse=True)
def _reset_globals():
    saved_cache = dict(pipeline._ext_cache)
    saved_inflight = dict(pipeline._ext_inflight)
    saved_prefetch = pipeline._PREFETCH_ENABLED
    saved_retries = pipeline.RETRIES_EFFECTIFS
    saved_delay = pipeline.DELAI_RETRY_EFFECTIF
    saved_access = dict(rl._domain_last_access)
    pipeline._ext_cache.clear()
    pipeline._ext_inflight.clear()
    rl._domain_last_access.clear()
    yield
    pipeline._ext_cache.clear()
    pipeline._ext_cache.update(saved_cache)
    pipeline._ext_inflight.clear()
    pipeline._ext_inflight.update(saved_inflight)
    pipeline._PREFETCH_ENABLED = saved_prefetch
    pipeline.RETRIES_EFFECTIFS = saved_retries
    pipeline.DELAI_RETRY_EFFECTIF = saved_delay
    rl._domain_last_access.clear()
    rl._domain_last_access.update(saved_access)


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


def _ep(url="https://anime-sama.to/catalogue/x/saison1/vostfr?ep=1"):
    return {"titre": "Show", "saison": 1, "episode": 1, "langue": "VOSTFR", "url": url}


def _no_skip(monkeypatch):
    monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: False)
    monkeypatch.setattr(pipeline, "_fichier_existe", lambda d, n: False)


def _lecteurs_async(monkeypatch, lecteurs, recorder=None):
    async def get(url):
        if recorder is not None:
            recorder.append(url)
        return list(lecteurs)

    monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", get)


LECTEUR = {"src": "https://player.example/embed", "host": "player.example"}


class TestDomainStrategyExceptBranches:
    def test_get_domain_swallows_urlparse_error(self, monkeypatch):
        def boom(_u):
            raise ValueError("bad url")

        monkeypatch.setattr(ds, "urlparse", boom)
        assert ds.get_domain("https://x/y") == ""

    def test_lecteur_url_valide_swallows_urlparse_error(self, monkeypatch):
        def boom(_u):
            raise ValueError("bad url")

        monkeypatch.setattr(ds, "urlparse", boom)
        assert ds.lecteur_url_valide({"src": "https://x/y"}) is False


class TestRateLimiterBranches:
    def test_domain_mark_used_empty_domain_is_noop(self):
        before = dict(rl._domain_last_access)
        rl.domain_mark_used("")
        assert rl._domain_last_access == before

    def test_domain_apply_penalty_empty_domain_is_noop(self):
        before = dict(rl._domain_last_access)
        rl.domain_apply_penalty("")
        assert rl._domain_last_access == before

    def test_domain_wait_purges_when_over_fifty(self, monkeypatch):
        purged = []
        monkeypatch.setattr(
            rl, "_purger_cache_verrou_tenu", lambda: purged.append(True)
        )
        for i in range(60):
            rl._domain_last_access[f"d{i}.tld"] = 0.0

        asyncio.run(rl.domain_wait("new.example"))

        assert purged == [True]

    def test_domain_mark_used_purges_when_over_fifty(self, monkeypatch):
        purged = []
        monkeypatch.setattr(
            rl, "_purger_cache_verrou_tenu", lambda: purged.append(True)
        )
        for i in range(60):
            rl._domain_last_access[f"d{i}.tld"] = 0.0

        rl.domain_mark_used("new.example")

        assert purged == [True]


class TestRuntimeHistoriqueAppendBranches:
    def test_history_append_swallows_attribute_error(self):
        queue = SimpleNamespace()
        runtime._historique_append(queue, {"succes": 1})

    def test_store_append_history_failure_swallowed(self):
        class BadStore:
            def append_history(self, _e):
                raise RuntimeError("store down")

        queue = SimpleNamespace(_history=[], _store=BadStore())
        runtime._historique_append(queue, {"succes": 0})

        assert queue._history == [{"succes": 0}]

    def test_metrics_update_failure_swallowed(self, monkeypatch):
        class BoomMetrics:
            def incr(self, *a, **k):
                raise RuntimeError("metrics down")

        import engine.observability.metrics as metrics_mod

        monkeypatch.setattr(metrics_mod, "metrics", BoomMetrics())

        queue = SimpleNamespace(_history=[])
        runtime._historique_append(queue, {"succes": 1, "echoues": 0, "skipped": 0})

        assert queue._history == [{"succes": 1, "echoues": 0, "skipped": 0}]


class TestRuntimeArmerTokenLegacyError:
    def test_legacy_token_assignment_typeerror_swallowed(self, monkeypatch):
        async def fake_sleep(_):
            raise AssertionError("sleep must not run when item assignment fails")

        monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)

        token = ("immutable",)
        asyncio.run(runtime._armer_token_annulation(SimpleNamespace(_cancelled=token)))


class TestPrefetchExtractionExceptBranches:
    def test_cancelled_error_propagates(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

        async def cancel(_):
            raise asyncio.CancelledError()

        monkeypatch.setattr(pipeline.asyncio, "sleep", cancel)

        ep = _ep()
        q = FakeQueue()
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(pipeline.prefetch_extraction(ep, q))
        assert ep["url"] not in pipeline._ext_inflight

    def test_generic_exception_swallowed_and_inflight_cleared(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

        async def no_sleep(_):
            return None

        monkeypatch.setattr(pipeline.asyncio, "sleep", no_sleep)

        async def boom(url):
            raise RuntimeError("scrape exploded")

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", boom)

        ep = _ep()
        q = FakeQueue()
        asyncio.run(pipeline.prefetch_extraction(ep, q))

        assert ep["url"] not in pipeline._ext_inflight
        assert ep["url"] not in pipeline._ext_cache


class TestTraiterEpisodeMetricsAndPrefetch:
    def test_episode_latency_metrics_failure_swallowed(self, monkeypatch):
        _no_skip(monkeypatch)

        from engine.observability.metrics import metrics

        def boom(*a, **k):
            raise RuntimeError("observe down")

        monkeypatch.setattr(metrics, "observe", boom)

        async def get(url):
            return []

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", get)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "echoues"

    def test_inflight_wait_for_failure_falls_back_to_cache(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        ep = _ep()

        async def get(url):
            return [LECTEUR]

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", get)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def boom_wait_for(_aw, timeout=0):
            raise TimeoutError()

        monkeypatch.setattr(pipeline.asyncio, "wait_for", boom_wait_for)

        async def ytdlp(*a, **k):
            return "normal.mp4"

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        async def runner():
            fut = asyncio.get_running_loop().create_future()
            fut.set_result({"url": "https://cdn/ignored.m3u8", "headers": {}})
            pipeline._ext_inflight[ep["url"]] = fut
            q = FakeQueue()
            return await pipeline._traiter_un_episode(ep, 0, 1, "Show", q)

        out = asyncio.run(runner())
        assert out == "succes"

    def test_prefetched_path_generic_exception_falls_through(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
        ep = _ep()
        pipeline._ext_cache_set(ep["url"], {"url": "https://cdn/pref.m3u8", "headers": {}})

        seen = []
        _lecteurs_async(monkeypatch, [LECTEUR], recorder=seen)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def lancer_boom(*a, **k):
            raise ValueError("prefetched failed")

        async def ytdlp(*a, **k):
            return "normal.mp4"

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer_boom)
        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(ep, 0, 1, "Show", q))

        assert out == "succes"
        assert seen == [ep["url"]]

    def test_prefetched_path_download_cancelled_propagates(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        ep = _ep()
        pipeline._ext_cache_set(ep["url"], {"url": "https://cdn/pref.m3u8", "headers": {}})

        _lecteurs_async(monkeypatch, [LECTEUR])

        async def lancer_cancel(*a, **k):
            raise DownloadCancelled()

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer_cancel)

        q = FakeQueue()
        with pytest.raises(DownloadCancelled):
            asyncio.run(pipeline._traiter_un_episode(ep, 0, 1, "Show", q))


class TestRetryLoopCancelledError:
    def test_cancelled_error_in_loop_propagates(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 3)
        _lecteurs_async(monkeypatch, [LECTEUR])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def ytdlp(*a, **k):
            raise asyncio.CancelledError()

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))


class TestYtdlpSurLecteurs:
    def test_no_lecteurs_with_src_returns_none(self):
        q = FakeQueue()
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([{"host": "h"}], "/tmp", "ep", "[x]", q)
        )
        assert out is None

    def test_cancelled_before_loop_body_breaks(self, monkeypatch):
        async def must_not_wait(domain):
            raise AssertionError("domain_wait must not run when cancelled before body")

        monkeypatch.setattr(pipeline, "domain_wait", must_not_wait)
        q = FakeQueue()
        q._cancelled.set()
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q)
        )
        assert out is None

    def test_cancelled_after_domain_wait_breaks(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)
        q = FakeQueue()

        async def wait_then_cancel(domain):
            q._cancelled.set()

        monkeypatch.setattr(pipeline, "domain_wait", wait_then_cancel)

        async def must_not_pool(*a, **k):
            raise AssertionError("pool must not run when cancelled after domain_wait")

        monkeypatch.setattr(pipeline, "_run_in_pool", must_not_pool)
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q)
        )
        assert out is None

    def test_on_progress_callback_emits_progress(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

        async def no_wait(domain):
            return None

        monkeypatch.setattr(pipeline, "domain_wait", no_wait)

        async def pool(fn, src, dossier, nom_ep, headers, cancelled, on_progress):
            on_progress(42, "halfway")
            return "out.mp4"

        monkeypatch.setattr(pipeline, "_run_in_pool", pool)
        q = FakeQueue()
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q, referer="r")
        )
        assert out == "out.mp4"
        progress = [d for ev, d in q.events if ev == "episode_progress"]
        assert {"pct": 42, "line": "halfway", "ep": "[x]"} in progress

    def test_ratelimit_applies_penalty_and_tries_next(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

        async def no_wait(domain):
            return None

        monkeypatch.setattr(pipeline, "domain_wait", no_wait)

        penalised = []
        monkeypatch.setattr(pipeline, "domain_apply_penalty", lambda d: penalised.append(d))
        monkeypatch.setattr(pipeline, "domain_penalty", lambda d: 30.0)

        import engine.download.methods.ytdlp_engine as ytdlp_mod

        async def pool_ratelimit(*a, **k):
            raise ytdlp_mod.RateLimitError("403")

        monkeypatch.setattr(pipeline, "_run_in_pool", pool_ratelimit)
        q = FakeQueue()
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q)
        )
        assert out is None
        assert penalised
        lines = [d["line"] for ev, d in q.events if ev == "episode_progress"]
        assert any("occupé" in line for line in lines)

    def test_download_cancelled_propagates(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

        async def no_wait(domain):
            return None

        monkeypatch.setattr(pipeline, "domain_wait", no_wait)

        async def pool_cancel(*a, **k):
            raise DownloadCancelled()

        monkeypatch.setattr(pipeline, "_run_in_pool", pool_cancel)
        q = FakeQueue()
        with pytest.raises(DownloadCancelled):
            asyncio.run(
                pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q)
            )

    def test_runtimeerror_swallowed_and_returns_none(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

        async def no_wait(domain):
            return None

        monkeypatch.setattr(pipeline, "domain_wait", no_wait)

        async def pool_runtime(*a, **k):
            raise RuntimeError("yt-dlp error")

        monkeypatch.setattr(pipeline, "_run_in_pool", pool_runtime)
        q = FakeQueue()
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q)
        )
        assert out is None

    def test_generic_exception_swallowed_and_returns_none(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

        async def no_wait(domain):
            return None

        monkeypatch.setattr(pipeline, "domain_wait", no_wait)

        async def pool_generic(*a, **k):
            raise ValueError("unexpected")

        monkeypatch.setattr(pipeline, "_run_in_pool", pool_generic)
        q = FakeQueue()
        out = asyncio.run(
            pipeline._ytdlp_sur_lecteurs([LECTEUR], "/tmp", "ep", "[x]", q)
        )
        assert out is None


class TestPipelinePlaywrightMetricsAndDedup:
    def test_finally_metrics_failure_swallowed(self, monkeypatch):
        from engine.observability.metrics import metrics

        def boom(*a, **k):
            raise RuntimeError("incr down")

        monkeypatch.setattr(metrics, "incr", boom)

        async def impl(lecteurs, ep_label, queue):
            return {"url": "https://cdn/x.m3u8"}

        monkeypatch.setattr(pipeline, "_pipeline_playwright_impl", impl)

        q = FakeQueue()
        out = asyncio.run(pipeline._pipeline_playwright([LECTEUR], "[x]", q))
        assert out == {"url": "https://cdn/x.m3u8"}

    def test_non_dict_and_duplicate_src_are_skipped(self, monkeypatch):
        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)

        captured = {}

        async def parallele(lecteurs, timeout=0, on_win=None):
            captured["n"] = len(lecteurs)
            return {"url": "https://cdn/dedup.m3u8"}

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteurs_parallele", parallele
        )

        lecteurs = [
            {"src": "https://dup.example/1", "host": "dup"},
            {"src": "https://dup.example/1", "host": "dup"},
            {"host": "nosrc"},
            "not-a-dict",
        ]
        q = FakeQueue()
        out = asyncio.run(pipeline._pipeline_playwright_impl(lecteurs, "[x]", q))
        assert out == {"url": "https://cdn/dedup.m3u8"}
        assert captured["n"] == 1


class TestPipelinePlaywrightImportError:
    def test_browser_extractor_import_error_returns_none(self, monkeypatch):
        import sys

        monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
        monkeypatch.setattr(pipeline, "host_disponible", lambda h: True)

        class FwdBreaker:
            async def call(self, fn, *args):
                return await fn(*args)

        monkeypatch.setattr(pipeline, "get_breaker", lambda h: FwdBreaker())

        async def parallele(lecteurs, timeout=0, on_win=None):
            return None

        async def seq(src, timeout):
            return None

        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteurs_parallele", parallele
        )
        monkeypatch.setattr(
            "engine.download.interceptor.intercepter_lecteur", seq
        )

        import types

        empty_mod = types.ModuleType("engine.download.extractor.browser_extractor")
        monkeypatch.setitem(
            sys.modules, "engine.download.extractor.browser_extractor", empty_mod
        )

        q = FakeQueue()
        out = asyncio.run(pipeline._pipeline_playwright_impl([LECTEUR], "[x]", q))
        assert out is None


def _engine(result, calls, name):
    def fn(url, dossier, nom, headers, cancelled, on_progress):
        calls.append(name)
        if isinstance(result, Exception):
            raise result
        return result

    fn.__name__ = name
    return fn


def _safe_disk(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
    monkeypatch.setattr(pipeline, "_espace_disque_suffisant", lambda d: True)


def _run_lancer(engines, q=None):
    q = q or FakeQueue()
    return asyncio.run(
        pipeline._lancer_download_pipeline(
            "https://cdn.example/v.m3u8", "/tmp/out", "ep", {}, q, "[x] S01E001",
            *engines,
        )
    )


class TestLancerDownloadEngineErrors:
    def test_ytdlp_runtimeerror_propagates(self, monkeypatch):
        _safe_disk(monkeypatch)
        calls = []
        with pytest.raises(RuntimeError, match="yt fatal"):
            _run_lancer((
                _engine(None, calls, "nm"),
                _engine(RuntimeError("yt fatal"), calls, "yt"),
                _engine("ff.mp4", calls, "ff"),
            ))
        assert calls == ["nm", "yt"]

    def test_ytdlp_generic_exception_falls_back_to_ffmpeg(self, monkeypatch):
        _safe_disk(monkeypatch)
        calls = []
        out = _run_lancer((
            _engine(None, calls, "nm"),
            _engine(ValueError("yt transient"), calls, "yt"),
            _engine("ff.mp4", calls, "ff"),
        ))
        assert out == "ff.mp4"
        assert calls == ["nm", "yt", "ff"]

    def test_ffmpeg_runtimeerror_propagates(self, monkeypatch):
        _safe_disk(monkeypatch)
        calls = []
        with pytest.raises(RuntimeError, match="ff fatal"):
            _run_lancer((
                _engine(None, calls, "nm"),
                _engine(None, calls, "yt"),
                _engine(RuntimeError("ff fatal"), calls, "ff"),
            ))
        assert calls == ["nm", "yt", "ff"]

    def test_ffmpeg_generic_exception_returns_none(self, monkeypatch):
        _safe_disk(monkeypatch)
        calls = []
        out = _run_lancer((
            _engine(None, calls, "nm"),
            _engine(None, calls, "yt"),
            _engine(ValueError("ff transient"), calls, "ff"),
        ))
        assert out is None
        assert calls == ["nm", "yt", "ff"]
