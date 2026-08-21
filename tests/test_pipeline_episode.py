import asyncio

import pytest

from engine.domain.exceptions import DownloadCancelled
from engine.download import pipeline
from engine.download.queue import CancelToken


@pytest.fixture(autouse=True)
def _reset_pipeline_globals():
    saved_cache = dict(pipeline._ext_cache)
    saved_inflight = dict(pipeline._ext_inflight)
    saved_prefetch = pipeline._PREFETCH_ENABLED
    saved_retries = pipeline.RETRIES_EFFECTIFS
    saved_delay = pipeline.DELAI_RETRY_EFFECTIF
    pipeline._ext_cache.clear()
    pipeline._ext_inflight.clear()
    yield
    pipeline._ext_cache.clear()
    pipeline._ext_cache.update(saved_cache)
    pipeline._ext_inflight.clear()
    pipeline._ext_inflight.update(saved_inflight)
    pipeline._PREFETCH_ENABLED = saved_prefetch
    pipeline.RETRIES_EFFECTIFS = saved_retries
    pipeline.DELAI_RETRY_EFFECTIF = saved_delay


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


def _ep(url="https://anime-sama.to/catalogue/x/saison1/vostfr?ep=1"):
    return {"titre": "Show", "saison": 1, "episode": 1, "langue": "VOSTFR", "url": url}


def _done_events(q):
    return [d for ev, d in q.events if ev == "episode_done"]


def _no_skip(monkeypatch):
    monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: False)
    monkeypatch.setattr(pipeline, "_fichier_existe", lambda d, n: False)


def _lecteurs_async(monkeypatch, lecteurs, recorder=None):
    async def get(url):
        if recorder is not None:
            recorder.append(url)
        return list(lecteurs)

    monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", get)


def _no_sleep(monkeypatch, recorder):
    async def sleep(delay):
        recorder.append(delay)
        return None

    monkeypatch.setattr(pipeline.asyncio, "sleep", sleep)


class TestYtdlpOnlyBranches:
    def test_ytdlp_player_returns_file_is_succes(self, monkeypatch):
        _no_skip(monkeypatch)
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        seen = []

        async def ytdlp(lecteurs, dossier, nom_ep, ep_label, queue, referer="", **_):
            seen.append(referer)
            return "file.mp4"

        async def must_not_pw(*a, **k):
            raise AssertionError("playwright must not run when ytdlp yields a file")

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)
        monkeypatch.setattr(pipeline, "_pipeline_playwright", must_not_pw)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "succes"
        assert seen == ["https://anime-sama.to/"]
        done = _done_events(q)
        assert done[-1] == {"ep": done[-1]["ep"], "succes": True, "skipped": False}

    def test_ytdlp_none_then_playwright_lancer_yields_file(self, monkeypatch):
        _no_skip(monkeypatch)
        ytdlp_lecteurs = [{"src": "https://h/v", "host": "h"}]
        _lecteurs_async(monkeypatch, ytdlp_lecteurs)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def ytdlp(*a, **k):
            return None

        pw_args = {}

        async def pipeline_pw(lecteurs, ep_label, queue):
            pw_args["lecteurs"] = lecteurs
            return {"url": "https://cdn/from_pw.m3u8", "headers": {"r": "1"}}

        lancer_args = {}

        async def lancer(url, dossier, nom_ep, headers, queue, ep_label, *engines):
            lancer_args["url"] = url
            lancer_args["headers"] = headers
            return "pw_file.mp4"

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)
        monkeypatch.setattr(pipeline, "_pipeline_playwright", pipeline_pw)
        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "succes"
        assert pw_args["lecteurs"] == ytdlp_lecteurs
        assert lancer_args["url"] == "https://cdn/from_pw.m3u8"
        assert lancer_args["headers"] == {"r": "1"}


class TestPlaywrightBranches:
    def test_playwright_lancer_yields_file_no_ytdlp_fallback(self, monkeypatch):
        _no_skip(monkeypatch)
        pw_lecteurs = [{"src": "https://p/v", "host": "p"}]
        _lecteurs_async(monkeypatch, pw_lecteurs)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: ([], list(lec)))

        seen = {}

        async def pipeline_pw(lecteurs, ep_label, queue):
            seen["pw"] = lecteurs
            return {"url": "https://cdn/pw.m3u8", "headers": {}}

        async def lancer(url, dossier, nom_ep, headers, queue, ep_label, *engines):
            seen["lancer_url"] = url
            return "pw.mp4"

        async def must_not_ytdlp(*a, **k):
            raise AssertionError("ytdlp fallback must not run after playwright file")

        monkeypatch.setattr(pipeline, "_pipeline_playwright", pipeline_pw)
        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer)
        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", must_not_ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "succes"
        assert seen["pw"] == pw_lecteurs
        assert seen["lancer_url"] == "https://cdn/pw.m3u8"

    def test_playwright_lancer_none_falls_back_to_ytdlp_on_playwright_lecteurs(self, monkeypatch):
        _no_skip(monkeypatch)
        pw_lecteurs = [{"src": "https://p/v", "host": "p"}]
        _lecteurs_async(monkeypatch, pw_lecteurs)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: ([], list(lec)))

        async def pipeline_pw(lecteurs, ep_label, queue):
            return {"url": "https://cdn/pw.m3u8", "headers": {}}

        async def lancer(*a, **k):
            return None

        ytdlp_calls = {}

        async def ytdlp(lecteurs, dossier, nom_ep, ep_label, queue, referer="", **_):
            ytdlp_calls["lecteurs"] = lecteurs
            ytdlp_calls["referer"] = referer
            return "ytdlp_fallback.mp4"

        monkeypatch.setattr(pipeline, "_pipeline_playwright", pipeline_pw)
        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer)
        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "succes"
        assert ytdlp_calls["lecteurs"] == pw_lecteurs
        assert ytdlp_calls["referer"] == "https://anime-sama.to/"

    def test_playwright_no_result_then_ytdlp_fallback(self, monkeypatch):
        _no_skip(monkeypatch)
        pw_lecteurs = [{"src": "https://p/v", "host": "p"}]
        _lecteurs_async(monkeypatch, pw_lecteurs)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: ([], list(lec)))

        async def pipeline_pw(lecteurs, ep_label, queue):
            return None

        async def must_not_lancer(*a, **k):
            raise AssertionError("lancer must not run when playwright yields no result")

        async def ytdlp(lecteurs, dossier, nom_ep, ep_label, queue, referer="", **_):
            return "ytdlp_only.mp4"

        monkeypatch.setattr(pipeline, "_pipeline_playwright", pipeline_pw)
        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", must_not_lancer)
        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "succes"


class TestRetryLoop:
    def test_first_attempt_none_second_file_sleep_between(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 2)
        monkeypatch.setattr(pipeline, "DELAI_RETRY_EFFECTIF", 7)
        sleeps = []
        _no_sleep(monkeypatch, sleeps)

        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        attempts = {"n": 0}

        async def ytdlp(*a, **k):
            attempts["n"] += 1
            return None if attempts["n"] == 1 else "file.mp4"

        async def must_not_pw(*a, **k):
            raise AssertionError("playwright must not run; ytdlp succeeds on retry")

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)
        monkeypatch.setattr(pipeline, "_pipeline_playwright", must_not_pw)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "succes"
        assert attempts["n"] == 2
        assert sleeps == [7]

    def test_all_retries_fail_returns_echoues_with_default_erreur(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 3)
        monkeypatch.setattr(pipeline, "DELAI_RETRY_EFFECTIF", 0)
        sleeps = []
        _no_sleep(monkeypatch, sleeps)

        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        attempts = {"n": 0}

        async def ytdlp(*a, **k):
            attempts["n"] += 1
            return None

        async def pipeline_pw(lecteurs, ep_label, queue):
            return None

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)
        monkeypatch.setattr(pipeline, "_pipeline_playwright", pipeline_pw)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "echoues"
        assert attempts["n"] == 3
        assert sleeps == [0, 0]
        done = _done_events(q)
        assert done[-1]["succes"] is False
        assert done[-1]["skipped"] is False
        assert done[-1]["erreur"] == "Aucune URL capturée"

    def test_runtimeerror_is_captured_as_erreur_and_retried(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 2)
        monkeypatch.setattr(pipeline, "DELAI_RETRY_EFFECTIF", 0)
        sleeps = []
        _no_sleep(monkeypatch, sleeps)

        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        attempts = {"n": 0}

        async def ytdlp(*a, **k):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("boom on the wire")
            return "recovered.mp4"

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "succes"
        assert attempts["n"] == 2
        assert sleeps == [0]

    def test_runtimeerror_every_attempt_yields_echoues_with_message(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 2)
        monkeypatch.setattr(pipeline, "DELAI_RETRY_EFFECTIF", 0)
        sleeps = []
        _no_sleep(monkeypatch, sleeps)

        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def ytdlp(*a, **k):
            raise RuntimeError("persistent network failure")

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "echoues"
        done = _done_events(q)
        assert done[-1]["erreur"] == "persistent network failure"

    def test_generic_exception_is_captured_and_truncated(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
        monkeypatch.setattr(pipeline, "DELAI_RETRY_EFFECTIF", 0)
        sleeps = []
        _no_sleep(monkeypatch, sleeps)

        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        long_msg = "x" * 500

        async def ytdlp(*a, **k):
            raise ValueError(long_msg)

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "echoues"
        done = _done_events(q)
        assert done[-1]["erreur"] == "x" * 200
        assert sleeps == []


class TestCancellation:
    def test_download_cancelled_propagates(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 3)
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def ytdlp(*a, **k):
            raise DownloadCancelled()

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        with pytest.raises(DownloadCancelled):
            asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))
        assert not _done_events(q)

    def test_cancelled_token_breaks_loop_before_subpipelines(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 3)
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def must_not_run(*a, **k):
            raise AssertionError("sub-pipeline must not run when cancelled before loop body")

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", must_not_run)
        monkeypatch.setattr(pipeline, "_pipeline_playwright", must_not_run)

        q = FakeQueue()
        q._cancelled.set()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "echoues"
        done = _done_events(q)
        assert done[-1]["erreur"] == "Aucune URL capturée"


class TestNoValidLecteurs:
    def test_partition_empty_both_yields_aucun_lecteur_valide(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
        monkeypatch.setattr(pipeline, "DELAI_RETRY_EFFECTIF", 0)
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: ([], []))

        async def must_not_run(*a, **k):
            raise AssertionError("no sub-pipeline runs when both partitions empty")

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", must_not_run)
        monkeypatch.setattr(pipeline, "_pipeline_playwright", must_not_run)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "echoues"
        done = _done_events(q)
        assert done[-1]["erreur"] == "Aucun lecteur valide"

    def test_get_lecteurs_raises_is_treated_as_no_player(self, monkeypatch):
        _no_skip(monkeypatch)

        async def boom(url):
            raise RuntimeError("scrape exploded")

        monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", boom)

        async def must_not_partition(lec):
            raise AssertionError("partition must not run when no lecteurs")

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

        assert out == "echoues"
        done = _done_events(q)
        assert done[-1]["erreur"] == "Aucun lecteur sur la page"


class TestPrefetch:
    def test_prefetch_cache_hit_skips_get_lecteurs(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        ep = _ep()
        pipeline._ext_cache_set(ep["url"], {"url": "https://cdn/pref.m3u8", "headers": {"h": "1"}})

        seen = []
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}], recorder=seen)

        lancer_args = {}

        async def lancer(url, dossier, nom_ep, headers, queue, ep_label, *engines):
            lancer_args["url"] = url
            lancer_args["headers"] = headers
            return "prefetched.mp4"

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(ep, 0, 1, "Show", q))

        assert out == "succes"
        assert seen == []
        assert lancer_args["url"] == "https://cdn/pref.m3u8"
        assert lancer_args["headers"] == {"h": "1"}
        done = _done_events(q)
        assert done[-1] == {"ep": done[-1]["ep"], "succes": True, "skipped": False}

    def test_prefetch_hit_but_lancer_none_falls_through_to_normal(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
        ep = _ep()
        pipeline._ext_cache_set(ep["url"], {"url": "https://cdn/pref.m3u8", "headers": {}})

        seen = []
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}], recorder=seen)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def lancer(*a, **k):
            return None

        async def ytdlp(*a, **k):
            return "normal_path.mp4"

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer)
        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(ep, 0, 1, "Show", q))

        assert out == "succes"
        assert seen == [ep["url"]]

    def test_prefetch_miss_empty_cache_falls_through_to_normal(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
        ep = _ep()

        seen = []
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}], recorder=seen)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def must_not_lancer(*a, **k):
            raise AssertionError("lancer must not run on prefetch miss")

        async def ytdlp(*a, **k):
            return "normal.mp4"

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", must_not_lancer)
        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        q = FakeQueue()
        out = asyncio.run(pipeline._traiter_un_episode(ep, 0, 1, "Show", q))

        assert out == "succes"
        assert seen == [ep["url"]]

    def test_prefetch_via_inflight_future_yields_file(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        ep = _ep()

        seen = []
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}], recorder=seen)

        lancer_args = {}

        async def lancer(url, dossier, nom_ep, headers, queue, ep_label, *engines):
            lancer_args["url"] = url
            return "inflight.mp4"

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", lancer)

        async def runner():
            fut = asyncio.get_running_loop().create_future()
            fut.set_result({"url": "https://cdn/inflight.m3u8", "headers": {}})
            pipeline._ext_inflight[ep["url"]] = fut
            q = FakeQueue()
            return await pipeline._traiter_un_episode(ep, 0, 1, "Show", q), q

        out, q = asyncio.run(runner())

        assert out == "succes"
        assert seen == []
        assert lancer_args["url"] == "https://cdn/inflight.m3u8"

    def test_prefetch_inflight_none_result_then_cache_then_normal(self, monkeypatch):
        _no_skip(monkeypatch)
        monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)
        monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
        ep = _ep()

        seen = []
        _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}], recorder=seen)
        monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

        async def must_not_lancer(*a, **k):
            raise AssertionError("lancer must not run when inflight yields None and cache empty")

        async def ytdlp(*a, **k):
            return "normal_after_inflight.mp4"

        monkeypatch.setattr(pipeline, "_lancer_download_pipeline", must_not_lancer)
        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)

        async def runner():
            fut = asyncio.get_running_loop().create_future()
            fut.set_result(None)
            pipeline._ext_inflight[ep["url"]] = fut
            q = FakeQueue()
            return await pipeline._traiter_un_episode(ep, 0, 1, "Show", q)

        out = asyncio.run(runner())

        assert out == "succes"
        assert seen == [ep["url"]]


def test_traiter_un_episode_runs_within_task_context(monkeypatch):
    from engine.observability.context import get_task_id

    _no_skip(monkeypatch)
    seen = {}

    async def get(url):
        seen["tid"] = get_task_id()
        return []

    monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", get)
    q = FakeQueue()
    out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

    assert out == "echoues"
    assert len(seen["tid"]) == 6
    assert get_task_id() == ""


def test_traiter_un_episode_logs_lecteur_cascade(monkeypatch, caplog):
    import logging

    _no_skip(monkeypatch)
    _lecteurs_async(
        monkeypatch,
        [{"src": "https://h1/v", "host": "h1"}, {"src": "https://h2/v", "host": "h2"}],
    )
    monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

    async def fail(*a, **k):
        return None

    monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", fail)
    monkeypatch.setattr(pipeline, "_pipeline_playwright", fail)

    with caplog.at_level(logging.INFO, logger="engine.download.pipeline"):
        out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", FakeQueue()))

    assert out == "echoues"
    assert any("2 lecteur" in r.getMessage() for r in caplog.records)


def test_traiter_un_episode_observes_episode_latency(monkeypatch):
    from engine.observability.metrics import metrics

    metrics.reset()
    _no_skip(monkeypatch)

    async def get(url):
        return []

    monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", get)
    asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", FakeQueue()))

    assert metrics.percentiles("lat_episode_s")["count"] == 1
    metrics.reset()
