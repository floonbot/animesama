import asyncio
import os
import threading

import pytest

import engine.download.worker as worker
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


def test_non_dict_item_is_noop():
    queue = FakeQueue()
    asyncio.run(worker.traiter_item(["not", "a", "dict"], queue))
    assert queue.events == []
    assert queue._history == []


def test_routing_scan(monkeypatch):
    ran = []

    async def fake_scan(item, q):
        ran.append("scan")

    async def fake_direct(item, q):
        ran.append("direct")

    async def fake_episode(item, q):
        ran.append("episode")

    monkeypatch.setattr(worker, "_traiter_scan", fake_scan)
    monkeypatch.setattr(worker, "_traiter_direct", fake_direct)
    monkeypatch.setattr(worker, "_traiter_episode", fake_episode)

    asyncio.run(worker.traiter_item({"_scan": True, "oeuvre": "X"}, FakeQueue()))
    assert ran == ["scan"]


def test_routing_direct(monkeypatch):
    ran = []

    async def fake_scan(item, q):
        ran.append("scan")

    async def fake_direct(item, q):
        ran.append("direct")

    async def fake_episode(item, q):
        ran.append("episode")

    monkeypatch.setattr(worker, "_traiter_scan", fake_scan)
    monkeypatch.setattr(worker, "_traiter_direct", fake_direct)
    monkeypatch.setattr(worker, "_traiter_episode", fake_episode)

    asyncio.run(worker.traiter_item({"_direct": True, "url_stream": "u"}, FakeQueue()))
    assert ran == ["direct"]


def test_routing_episode_default(monkeypatch):
    ran = []

    async def fake_scan(item, q):
        ran.append("scan")

    async def fake_direct(item, q):
        ran.append("direct")

    async def fake_episode(item, q):
        ran.append("episode")

    monkeypatch.setattr(worker, "_traiter_scan", fake_scan)
    monkeypatch.setattr(worker, "_traiter_direct", fake_direct)
    monkeypatch.setattr(worker, "_traiter_episode", fake_episode)

    asyncio.run(worker.traiter_item({"episodes": [{"url": "u"}]}, FakeQueue()))
    assert ran == ["episode"]


def test_routing_direct_sets_task_context(monkeypatch):
    from engine.observability.context import get_task_id

    seen = {}

    async def fake_direct(item, q):
        seen["tid"] = get_task_id()

    monkeypatch.setattr(worker, "_traiter_direct", fake_direct)
    asyncio.run(worker.traiter_item({"_direct": True, "url_stream": "u"}, FakeQueue()))
    assert len(seen["tid"]) == 6
    assert get_task_id() == ""


def test_routing_scan_sets_task_context(monkeypatch):
    from engine.observability.context import get_task_id

    seen = {}

    async def fake_scan(item, q):
        seen["tid"] = get_task_id()

    monkeypatch.setattr(worker, "_traiter_scan", fake_scan)
    asyncio.run(worker.traiter_item({"_scan": True, "oeuvre": "X"}, FakeQueue()))
    assert len(seen["tid"]) == 6


def test_routing_episode_has_no_batch_task_context(monkeypatch):
    from engine.observability.context import get_task_id

    seen = {}

    async def fake_episode(item, q):
        seen["tid"] = get_task_id()

    monkeypatch.setattr(worker, "_traiter_episode", fake_episode)
    asyncio.run(worker.traiter_item({"episodes": [{"url": "u"}]}, FakeQueue()))
    assert seen["tid"] == ""


def test_episode_tally_events_history_and_metrics(reset_metrics, monkeypatch):
    eps = [
        {"titre": "Naruto", "langue": "VOSTFR", "tag": "ok1"},
        {"titre": "Naruto", "langue": "VOSTFR", "tag": "ok2"},
        {"titre": "Naruto", "langue": "VOSTFR", "tag": "skip"},
        {"titre": "Naruto", "langue": "VOSTFR", "tag": "fail"},
    ]
    results = {"ok1": "succes", "ok2": "succes", "skip": "skipped", "fail": "echoues"}

    async def fake_un_episode(ep, i, total, titre, q):
        return results[ep["tag"]]

    async def fake_sleep(_d):
        return None

    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: eps)
    monkeypatch.setattr(worker, "_traiter_un_episode", fake_un_episode)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", False)

    queue = FakeQueue()
    asyncio.run(worker._traiter_episode({"episodes": eps}, queue))

    done = _events_of(queue, "anime_done")
    assert len(done) == 1
    entree = done[0]
    assert entree["titre"] == "Naruto"
    assert entree["langue"] == "VOSTFR"
    assert entree["succes"] == 2
    assert entree["skipped"] == 1
    assert entree["echoues"] == 1
    assert entree["annule"] is False

    assert queue._history == [entree]

    snap = reset_metrics.snapshot()
    assert snap.get("episodes_succes") == 2
    assert snap.get("episodes_skipped") == 1
    assert snap.get("episodes_echoues") == 1


def test_episode_empty_list_emits_anime_done_zero(reset_metrics, monkeypatch):
    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: [])

    queue = FakeQueue()
    asyncio.run(worker._traiter_episode({"ep": {"titre": "Bleach"}}, queue))

    done = _events_of(queue, "anime_done")
    assert len(done) == 1
    assert done[0]["titre"] == "Bleach"
    assert done[0]["erreur"] == "Aucun épisode fourni"
    assert done[0]["succes"] == 0
    assert done[0]["echoues"] == 0
    assert done[0]["skipped"] == 0
    assert queue._history == []
    assert reset_metrics.snapshot() == {}


def test_episode_stops_on_cancellation(reset_metrics, monkeypatch):
    eps = [
        {"titre": "One Piece", "langue": "VF", "tag": "a"},
        {"titre": "One Piece", "langue": "VF", "tag": "b"},
    ]
    seen = []

    async def fake_un_episode(ep, i, total, titre, q):
        seen.append(ep["tag"])
        return "succes"

    async def fake_sleep(_d):
        return None

    monkeypatch.setattr(worker, "_normaliser_episodes", lambda item: eps)
    monkeypatch.setattr(worker, "_traiter_un_episode", fake_un_episode)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", False)

    queue = FakeQueue()
    queue._cancelled.set()
    asyncio.run(worker._traiter_episode({"episodes": eps}, queue))

    assert seen == []
    done = _events_of(queue, "anime_done")
    assert len(done) == 1
    assert done[0]["annule"] is True
    assert done[0]["succes"] == 0


def test_direct_success_with_real_file(reset_metrics, monkeypatch, tmp_path):
    real = tmp_path / "video.mp4"
    real.write_bytes(b"x" * 10)

    called = []

    async def fake_run_in_pool(fn, *args):
        called.append(args)
        return str(real)

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: True)

    queue = FakeQueue()
    asyncio.run(worker._traiter_direct({"_direct": True, "nom": "Film", "url_stream": "https://ok/x"}, queue))

    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["nom"] == "Film"
    assert done[0]["succes"] is True
    assert done[0]["annule"] is False
    assert len(called) == 1
    assert queue._history[-1]["succes"] == 1
    assert queue._history[-1]["echoues"] == 0


def test_direct_success_false_when_file_missing(reset_metrics, monkeypatch):
    async def fake_run_in_pool(fn, *args):
        return "Z:/does/not/exist/none.mp4"

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: True)

    queue = FakeQueue()
    asyncio.run(worker._traiter_direct({"nom": "Film", "url_stream": "https://ok/x"}, queue))

    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is False
    assert queue._history[-1]["echoues"] == 1
    assert queue._history[-1]["succes"] == 0


def test_direct_ssrf_refused_skips_pool(reset_metrics, monkeypatch):
    called = []

    async def fake_run_in_pool(fn, *args):
        called.append(args)
        return "anything"

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda url: False)

    queue = FakeQueue()
    asyncio.run(worker._traiter_direct({"nom": "Bad", "url_stream": "http://169.254.169.254/"}, queue))

    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is False
    assert "169.254.169.254" in done[0]["erreur"]
    assert "SSRF" in done[0]["erreur"]
    assert called == []
    assert queue._history[-1]["echoues"] == 1


def test_direct_missing_url(reset_metrics, monkeypatch):
    called = []

    async def fake_run_in_pool(fn, *args):
        called.append(args)
        return "anything"

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)

    queue = FakeQueue()
    asyncio.run(worker._traiter_direct({"nom": "NoUrl"}, queue))

    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is False
    assert done[0]["erreur"] == "URL manquante"
    assert called == []
    assert queue._history[-1]["echoues"] == 1


def test_scan_success_invalidates_library(reset_metrics, monkeypatch, tmp_path):
    target = str(tmp_path / "scandir")

    async def fake_run_in_pool(fn, *args):
        return target

    invalidated = []
    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr(
        "engine.library.scanner.invalider_cache_librairie",
        lambda: invalidated.append(True),
    )

    queue = FakeQueue()
    item = {"_scan": True, "nom": "Berserk", "oeuvre": "berserk", "lang": "vf", "chapitres": ["1", "2"]}
    asyncio.run(worker._traiter_scan(item, queue))

    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["nom"] == "Berserk"
    assert done[0]["succes"] is True
    assert invalidated == [True]
    assert queue._history[-1]["succes"] == 1
    assert queue._history[-1]["echoues"] == 0


def test_scan_ok_true_without_os_path_exists(reset_metrics, monkeypatch):
    async def fake_run_in_pool(fn, *args):
        return "Z:/nonexistent/scan/path"

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)
    monkeypatch.setattr("engine.library.scanner.invalider_cache_librairie", lambda: None)

    queue = FakeQueue()
    item = {"nom": "Vinland", "oeuvre": "vinland", "lang": "vf", "chapitres": ["7"]}
    asyncio.run(worker._traiter_scan(item, queue))

    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is True
    assert not os.path.exists("Z:/nonexistent/scan/path")
    assert queue._history[-1]["succes"] == 1


def test_scan_invalid_missing_oeuvre(reset_metrics, monkeypatch):
    called = []

    async def fake_run_in_pool(fn, *args):
        called.append(args)
        return "x"

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)

    queue = FakeQueue()
    asyncio.run(worker._traiter_scan({"nom": "NoWork", "chapitres": ["1"]}, queue))

    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["succes"] is False
    assert done[0]["erreur"] == "Scan invalide"
    assert called == []
    assert queue._history[-1]["echoues"] == 1


def test_scan_invalid_missing_chapitres(reset_metrics, monkeypatch):
    called = []

    async def fake_run_in_pool(fn, *args):
        called.append(args)
        return "x"

    monkeypatch.setattr(worker, "_run_in_pool", fake_run_in_pool)

    queue = FakeQueue()
    asyncio.run(worker._traiter_scan({"nom": "Empty", "oeuvre": "empty", "chapitres": []}, queue))

    done = _events_of(queue, "episode_done")
    assert len(done) == 1
    assert done[0]["erreur"] == "Scan invalide"
    assert called == []
