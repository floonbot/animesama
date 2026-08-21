import asyncio
import threading

import pytest

import engine.download.worker as worker
from engine.domain.exceptions import DownloadCancelled
from engine.download.queue import CancelToken
from engine.observability.metrics import metrics


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self._state_lock = threading.Lock()
        self._history = []
        self._store = None
        self.events = []

    def emit(self, ev, data):
        self.events.append((ev, data))

    def statut(self):
        return {}


@pytest.fixture
def reset_metrics():
    metrics.reset()
    yield metrics
    metrics.reset()


def _events_of(queue, name):
    return [data for ev, data in queue.events if ev == name]


def test_direct_cancelled_emits_dl_annule(reset_metrics, monkeypatch):
    async def fake_run_in_pool(fn, *args):
        raise DownloadCancelled()

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: True)

    queue = FakeQueue()
    asyncio.run(worker._traiter_direct({"nom": "Film", "url_stream": "https://ok/x"}, queue))

    assert _events_of(queue, "dl_annule") == [{"nom": "Film"}]
    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["annule"] is True
    assert done[0]["succes"] is False
    assert queue._history[-1]["succes"] == 0
    assert queue._history[-1]["echoues"] == 0


def test_direct_runtime_error_records_failure(reset_metrics, monkeypatch):
    async def fake_run_in_pool(fn, *args):
        raise RuntimeError("boom-engine")

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: True)

    queue = FakeQueue()
    asyncio.run(worker._traiter_direct({"nom": "Film", "url_stream": "https://ok/x"}, queue))

    assert _events_of(queue, "dl_annule") == []
    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is False
    assert done[0]["annule"] is False
    assert done[0]["erreur"] == "boom-engine"
    assert queue._history[-1]["echoues"] == 1
    assert queue._history[-1]["succes"] == 0


def test_direct_runtime_error_truncates_message(reset_metrics, monkeypatch):
    async def fake_run_in_pool(fn, *args):
        raise RuntimeError("E" * 500)

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: True)

    queue = FakeQueue()
    asyncio.run(worker._traiter_direct({"nom": "Film", "url_stream": "https://ok/x"}, queue))

    done = _events_of(queue, "episode_done")
    assert done[0]["erreur"] == "E" * 200


def test_scan_cancelled_emits_dl_annule(reset_metrics, monkeypatch):
    async def fake_run_in_pool(fn, *args):
        raise DownloadCancelled()

    invalidated = []
    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr(
        "engine.library.scanner.invalider_cache_librairie",
        lambda: invalidated.append(True),
    )

    queue = FakeQueue()
    item = {"nom": "Berserk", "oeuvre": "berserk", "lang": "vf", "chapitres": ["1"]}
    asyncio.run(worker._traiter_scan(item, queue))

    assert _events_of(queue, "dl_annule") == [{"nom": "Berserk"}]
    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["annule"] is True
    assert done[0]["succes"] is False
    assert queue._history[-1]["echoues"] == 0
    assert queue._history[-1]["succes"] == 0
    assert invalidated == [True]


def test_scan_generic_exception_records_error(reset_metrics, monkeypatch):
    async def fake_run_in_pool(fn, *args):
        raise ValueError("scan-broke" + "Z" * 500)

    invalidated = []
    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr(
        "engine.library.scanner.invalider_cache_librairie",
        lambda: invalidated.append(True),
    )

    queue = FakeQueue()
    item = {"nom": "Berserk", "oeuvre": "berserk", "lang": "vf", "chapitres": ["1"]}
    asyncio.run(worker._traiter_scan(item, queue))

    assert _events_of(queue, "dl_annule") == []
    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is False
    assert done[0]["annule"] is False
    assert done[0]["erreur"] == ("scan-broke" + "Z" * 500)[:200]
    assert queue._history[-1]["echoues"] == 1
    assert invalidated == [True]


def test_episode_prefetch_task_scheduled_and_cancelled(reset_metrics, monkeypatch):
    eps = [
        {"titre": "Gintama", "langue": "VOSTFR", "tag": "a"},
        {"titre": "Gintama", "langue": "VOSTFR", "tag": "b"},
    ]
    started = []
    cancelled = []
    prefetched_args = []

    async def fake_prefetch(ep, q):
        prefetched_args.append((ep["tag"], q))
        started.append(ep["tag"])
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(ep["tag"])
            raise

    async def fake_un_episode(ep, i, total, titre, q):
        return "succes"

    real_sleep = asyncio.sleep

    async def fake_sleep(_d):
        await real_sleep(0)

    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: eps)
    monkeypatch.setattr(worker, "_traiter_un_episode", fake_un_episode)
    monkeypatch.setattr(worker, "prefetch_extraction", fake_prefetch)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", True)

    queue = FakeQueue()
    asyncio.run(worker._traiter_episode({"episodes": eps}, queue))

    assert [tag for tag, _q in prefetched_args] == ["b"]
    assert prefetched_args[0][1] is queue
    assert started == ["b"]
    assert cancelled == ["b"]
    done = _events_of(queue, "anime_done")
    assert len(done) == 1
    assert done[0]["succes"] == 2


def test_episode_timeout_signals_engine_and_counts_failure(reset_metrics, monkeypatch):
    eps = [{"titre": "Trigun", "langue": "VF", "tag": "a"}]
    signalled = []

    async def fake_attendre(coro, q):
        coro.close()
        raise TimeoutError()

    async def fake_un_episode(ep, i, total, titre, q):
        return "succes"

    async def fake_signaler(q):
        signalled.append(q)

    async def fake_sleep(_d):
        return None

    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: eps)
    monkeypatch.setattr(worker, "_traiter_un_episode", fake_un_episode)
    monkeypatch.setattr(worker, "_signaler_annulation_engine", fake_signaler)
    monkeypatch.setattr(worker, "_attendre_avec_budget", fake_attendre)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", False)

    queue = FakeQueue()
    asyncio.run(worker._traiter_episode({"episodes": eps}, queue))

    assert signalled == [queue]
    done = _events_of(queue, "anime_done")
    assert len(done) == 1
    assert done[0]["echoues"] == 1
    assert done[0]["succes"] == 0
    assert done[0]["skipped"] == 0


def test_episode_download_cancelled_mid_list_breaks(reset_metrics, monkeypatch):
    eps = [
        {"titre": "Berserk", "langue": "VF", "tag": "a"},
        {"titre": "Berserk", "langue": "VF", "tag": "b"},
        {"titre": "Berserk", "langue": "VF", "tag": "c"},
    ]
    seen = []

    async def fake_un_episode(ep, i, total, titre, q):
        seen.append(ep["tag"])
        if ep["tag"] == "b":
            raise DownloadCancelled()
        return "succes"

    async def fake_sleep(_d):
        return None

    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: eps)
    monkeypatch.setattr(worker, "_traiter_un_episode", fake_un_episode)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", False)

    queue = FakeQueue()
    asyncio.run(worker._traiter_episode({"episodes": eps}, queue))

    assert seen == ["a", "b"]
    done = _events_of(queue, "anime_done")
    assert len(done) == 1
    assert done[0]["succes"] == 1
    assert done[0]["echoues"] == 0
    assert done[0]["skipped"] == 0


def test_episode_generic_exception_counts_failure(reset_metrics, monkeypatch):
    eps = [
        {"titre": "Dorohedoro", "langue": "VF", "tag": "a"},
        {"titre": "Dorohedoro", "langue": "VF", "tag": "b"},
    ]
    seen = []

    async def fake_un_episode(ep, i, total, titre, q):
        seen.append(ep["tag"])
        if ep["tag"] == "a":
            raise ValueError("kaboom")
        return "succes"

    async def fake_sleep(_d):
        return None

    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: eps)
    monkeypatch.setattr(worker, "_traiter_un_episode", fake_un_episode)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", False)

    queue = FakeQueue()
    asyncio.run(worker._traiter_episode({"episodes": eps}, queue))

    assert seen == ["a", "b"]
    done = _events_of(queue, "anime_done")
    assert len(done) == 1
    assert done[0]["echoues"] == 1
    assert done[0]["succes"] == 1
    assert done[0]["skipped"] == 0
