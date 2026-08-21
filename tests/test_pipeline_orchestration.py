import asyncio

import pytest

from engine.domain.exceptions import DownloadCancelled
from engine.download import pipeline
from engine.download.queue import CancelToken


@pytest.fixture(autouse=True)
def _clear_ext_cache():
    pipeline._ext_cache.clear()
    pipeline._ext_inflight.clear()
    yield
    pipeline._ext_cache.clear()
    pipeline._ext_inflight.clear()


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


def _engine(result, calls, name):
    def fn(url, dossier, nom, headers, cancelled, on_progress):
        calls.append(name)
        if isinstance(result, Exception):
            raise result
        return result

    fn.__name__ = name
    return fn


def _safe_url(monkeypatch, ok=True):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: ok)


def _enough_disk(monkeypatch, ok=True):
    monkeypatch.setattr(pipeline, "_espace_disque_suffisant", lambda d: ok)


def _run_lancer(calls_engines):
    q = FakeQueue()
    return asyncio.run(
        pipeline._lancer_download_pipeline(
            "https://cdn.example/v.m3u8", "/tmp/out", "ep", {}, q, "[x] S01E001",
            *calls_engines,
        )
    )


class TestLancerDownloadPipeline:
    def test_nm3u8dl_success_stops_before_ytdlp_and_ffmpeg(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        calls = []
        out = _run_lancer((
            _engine("nm.mp4", calls, "nm"),
            _engine("yt.mp4", calls, "yt"),
            _engine("ff.mp4", calls, "ff"),
        ))
        assert out == "nm.mp4"
        assert calls == ["nm"]

    def test_falls_back_to_ytdlp_when_nm3u8dl_returns_none(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        calls = []
        out = _run_lancer((
            _engine(None, calls, "nm"),
            _engine("yt.mp4", calls, "yt"),
            _engine("ff.mp4", calls, "ff"),
        ))
        assert out == "yt.mp4"
        assert calls == ["nm", "yt"]

    def test_falls_back_to_ffmpeg_when_first_two_fail(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        calls = []
        out = _run_lancer((
            _engine(None, calls, "nm"),
            _engine(None, calls, "yt"),
            _engine("ff.mp4", calls, "ff"),
        ))
        assert out == "ff.mp4"
        assert calls == ["nm", "yt", "ff"]

    def test_all_engines_fail_returns_none(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        calls = []
        out = _run_lancer((
            _engine(None, calls, "nm"),
            _engine(None, calls, "yt"),
            _engine(None, calls, "ff"),
        ))
        assert out is None
        assert calls == ["nm", "yt", "ff"]

    def test_ssrf_rejected_url_calls_no_engine(self, monkeypatch):
        _safe_url(monkeypatch, ok=False)
        _enough_disk(monkeypatch)
        calls = []
        out = _run_lancer((
            _engine("nm.mp4", calls, "nm"),
            _engine("yt.mp4", calls, "yt"),
            _engine("ff.mp4", calls, "ff"),
        ))
        assert out is None
        assert calls == []

    def test_insufficient_disk_calls_no_engine(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch, ok=False)
        calls = []
        out = _run_lancer((
            _engine("nm.mp4", calls, "nm"),
            _engine("yt.mp4", calls, "yt"),
            _engine("ff.mp4", calls, "ff"),
        ))
        assert out is None
        assert calls == []

    def test_nm3u8dl_runtimeerror_propagates(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        calls = []
        with pytest.raises(RuntimeError):
            _run_lancer((
                _engine(RuntimeError("fatal"), calls, "nm"),
                _engine("yt.mp4", calls, "yt"),
                _engine("ff.mp4", calls, "ff"),
            ))
        assert calls == ["nm"]

    def test_nm3u8dl_generic_exception_falls_back_to_ytdlp(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        calls = []
        out = _run_lancer((
            _engine(ValueError("transient"), calls, "nm"),
            _engine("yt.mp4", calls, "yt"),
            _engine("ff.mp4", calls, "ff"),
        ))
        assert out == "yt.mp4"
        assert calls == ["nm", "yt"]

    def test_cancelled_after_nm3u8dl_raises_download_cancelled(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        calls = []
        q = FakeQueue()
        q._cancelled.set()
        with pytest.raises(DownloadCancelled):
            asyncio.run(pipeline._lancer_download_pipeline(
                "https://cdn.example/v.m3u8", "/tmp/out", "ep", {}, q, "[x] S01E001",
                _engine(None, calls, "nm"), _engine("yt.mp4", calls, "yt"), _engine("ff.mp4", calls, "ff"),
            ))
        assert calls == ["nm"]

    def test_cancelled_after_ytdlp_raises_before_ffmpeg(self, monkeypatch):
        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        calls = []
        q = FakeQueue()

        def yt_then_cancel(url, dossier, nom, headers, cancelled, on_progress):
            calls.append("yt")
            q._cancelled.set()
            return None

        yt_then_cancel.__name__ = "yt"
        with pytest.raises(DownloadCancelled):
            asyncio.run(pipeline._lancer_download_pipeline(
                "https://cdn.example/v.m3u8", "/tmp/out", "ep", {}, q, "[x] S01E001",
                _engine(None, calls, "nm"), yt_then_cancel, _engine("ff.mp4", calls, "ff"),
            ))
        assert calls == ["nm", "yt"]

    def test_ytdlp_ratelimit_falls_through_to_ffmpeg(self, monkeypatch):
        from engine.download.methods.ytdlp_engine import RateLimitError

        _safe_url(monkeypatch)
        _enough_disk(monkeypatch)
        monkeypatch.setattr(pipeline, "domain_apply_penalty", lambda d: None)
        calls = []

        def yt_ratelimited(url, dossier, nom, headers, cancelled, on_progress):
            calls.append("yt")
            raise RateLimitError("403")

        yt_ratelimited.__name__ = "yt"
        q = FakeQueue()
        result = asyncio.run(pipeline._lancer_download_pipeline(
            "https://cdn.example/v.m3u8", "/tmp/out", "ep", {}, q, "[x] S01E001",
            _engine(None, calls, "nm"), yt_ratelimited, _engine("ff.mp4", calls, "ff"),
        ))
        assert result == "ff.mp4"
        assert calls == ["nm", "yt", "ff"]


def _ep(url="https://anime-sama.to/catalogue/x/saison1/vostfr?ep=1"):
    return {"titre": "Show", "saison": 1, "episode": 1, "langue": "VOSTFR", "url": url}


class TestTraiterUnEpisode:
    def test_missing_url_returns_echoues(self, monkeypatch):
        q = FakeQueue()
        ep = _ep(url="")
        result = asyncio.run(pipeline._traiter_un_episode(ep, 0, 1, "Show", q))
        assert result == "echoues"
        done = [d for ev, d in q.events if ev == "episode_done"]
        assert done and done[-1]["erreur"] == "URL manquante"

    def test_already_present_is_skipped(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: True)
        monkeypatch.setattr(pipeline, "_fichier_existe", lambda d, n: True)
        q = FakeQueue()
        result = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))
        assert result == "skipped"

    def test_no_player_found_returns_echoues(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: False)

        async def no_lecteurs(url):
            return []

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", no_lecteurs)
        q = FakeQueue()
        result = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))
        assert result == "echoues"

    def test_ytdlp_player_success(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: False)

        async def some_lecteurs(url):
            return [{"src": "https://h/v", "host": "h"}]

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", some_lecteurs)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (lec, []))

        async def ytdlp_ok(*a, **k):
            return "file.mp4"

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp_ok)
        q = FakeQueue()
        result = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))
        assert result == "succes"

    def test_retry_then_success(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: False)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 2)
        monkeypatch.setattr(pipeline, "DELAI_RETRY_EFFECTIF", 0)

        async def no_sleep(_):
            return None

        monkeypatch.setattr(pipeline.asyncio, "sleep", no_sleep)

        async def some_lecteurs(url):
            return [{"src": "https://h/v", "host": "h"}]

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", some_lecteurs)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (lec, []))

        attempts = {"n": 0}

        async def ytdlp_flaky(*a, **k):
            attempts["n"] += 1
            return None if attempts["n"] == 1 else "file.mp4"

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp_flaky)
        q = FakeQueue()
        result = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))
        assert result == "succes"
        assert attempts["n"] == 2

    def test_prefetched_result_skips_player_retrieval(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: False)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        ep = _ep()
        pipeline._ext_cache_set(ep["url"], {"url": "https://cdn/x.m3u8", "headers": {}})

        called = {"lecteurs": False}

        async def must_not_run(url):
            called["lecteurs"] = True
            return []

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", must_not_run)

        async def lancer_ok(*a, **k):
            return "file.mp4"

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer_ok)
        q = FakeQueue()
        result = asyncio.run(pipeline._traiter_un_episode(ep, 0, 1, "Show", q))
        assert result == "succes"
        assert called["lecteurs"] is False


class TestPrefetchExtraction:
    def test_disabled_is_noop(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", False)
        q = FakeQueue()
        asyncio.run(pipeline.prefetch_extraction(_ep(), q))
        assert pipeline._ext_cache == {}

    def test_skips_when_already_cached(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        ep = _ep()
        pipeline._ext_cache_set(ep["url"], {"url": "u"})

        async def must_not_run(url):
            raise AssertionError("get_lecteurs_async must not be called when cached")

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", must_not_run)
        q = FakeQueue()
        asyncio.run(pipeline.prefetch_extraction(ep, q))


class TestExtCacheBoundary:
    def test_set_keeps_existing_at_exactly_fifty(self):
        for i in range(50):
            pipeline._ext_cache[f"k{i}"] = (pipeline.time.time(), {})
        pipeline._ext_cache_set("new", {"url": "u"})
        assert len(pipeline._ext_cache) == 51
        assert "k0" in pipeline._ext_cache

    def test_set_clears_when_strictly_over_fifty(self):
        for i in range(51):
            pipeline._ext_cache[f"k{i}"] = (pipeline.time.time(), {})
        pipeline._ext_cache_set("new", {"url": "u"})
        assert list(pipeline._ext_cache) == ["new"]
