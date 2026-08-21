import asyncio
import logging
from types import SimpleNamespace

import pytest

import engine.download.methods._proc_registry as proc_registry
from engine.download.queue import DownloadQueue


@pytest.fixture
def proc_recorder(monkeypatch):
    """Replace the proc-registry boundary with call recorders, restored on teardown."""
    calls = {"suspend": 0, "resume": 0, "kill": 0}
    suspend_return = {"n": 0}

    def fake_suspend_all():
        calls["suspend"] += 1
        return suspend_return["n"]

    def fake_resume_all():
        calls["resume"] += 1
        return 0

    def fake_kill_all_processes():
        calls["kill"] += 1
        return 0

    monkeypatch.setattr(proc_registry, "suspend_all", fake_suspend_all)
    monkeypatch.setattr(proc_registry, "resume_all", fake_resume_all)
    monkeypatch.setattr(proc_registry, "kill_all_processes", fake_kill_all_processes)
    return SimpleNamespace(calls=calls, suspend_return=suspend_return)


def test_pause_no_current_returns_false_and_skips_registry(proc_recorder):
    q = DownloadQueue()
    assert q.pause() is False
    assert proc_recorder.calls["suspend"] == 0


def test_pause_current_suspends_via_registry_and_emits(proc_recorder):
    q = DownloadQueue()
    q._current = {"nom": "X"}
    events = []
    q.subscribe(lambda ev, data: events.append((ev, data)))
    assert q.pause() is True
    assert proc_recorder.calls["suspend"] == 1
    assert q._paused.is_set() is True
    assert [ev for ev, _ in events] == ["queue_updated"]
    assert events[0][1]["en_pause"] is True


def test_pause_logs_count_when_processes_suspended(proc_recorder, caplog):
    q = DownloadQueue()
    q._current = {"nom": "X"}
    proc_recorder.suspend_return["n"] = 3
    with caplog.at_level(logging.INFO, logger="engine.download.queue"):
        assert q.pause() is True
    assert any(
        "3 process" in rec.getMessage() and rec.name == "engine.download.queue"
        for rec in caplog.records
    )


def test_pause_no_log_when_zero_processes_suspended(proc_recorder, caplog):
    q = DownloadQueue()
    q._current = {"nom": "X"}
    proc_recorder.suspend_return["n"] = 0
    with caplog.at_level(logging.INFO, logger="engine.download.queue"):
        assert q.pause() is True
    assert not any(
        "process de téléchargement suspendu" in rec.getMessage()
        for rec in caplog.records
    )


def test_reprendre_clears_pause_calls_resume_and_emits(proc_recorder):
    q = DownloadQueue()
    q._paused.set()
    events = []
    q.subscribe(lambda ev, data: events.append((ev, data)))
    assert q.reprendre() is True
    assert proc_recorder.calls["resume"] == 1
    assert q._paused.is_set() is False
    assert [ev for ev, _ in events] == ["queue_updated"]
    assert events[0][1]["en_pause"] is False


def test_annuler_calls_resume_and_kill_and_clears_pause(proc_recorder):
    q = DownloadQueue()
    q._current = {"nom": "C"}
    q._paused.set()
    assert q.annuler() is True
    assert proc_recorder.calls["resume"] == 1
    assert proc_recorder.calls["kill"] == 1
    assert q._paused.is_set() is False
    assert q._cancelled.is_cancelled() is True


def test_annuler_keeps_pending_items(proc_recorder, caplog):
    q = DownloadQueue()
    q._current = {"nom": "C"}
    q._queue.extend([{"i": 0}, {"i": 1}, {"i": 2}])
    with caplog.at_level(logging.INFO, logger="engine.download.queue"):
        assert q.annuler() is True
    assert [x["i"] for x in q._queue] == [0, 1, 2]
    assert not any("dropped" in rec.getMessage() for rec in caplog.records)


def test_cancel_task_threadsafe_running_loop_uses_call_soon():
    q = DownloadQueue()
    recorded = []
    sentinel_cancel = object()

    task = SimpleNamespace(done=lambda: False, cancel=sentinel_cancel)
    loop = SimpleNamespace(
        is_running=lambda: True,
        call_soon_threadsafe=lambda fn: recorded.append(fn),
    )
    q._task = task
    q._loop = loop
    q._cancel_task_threadsafe()
    assert recorded == [sentinel_cancel]


def test_cancel_task_threadsafe_no_running_loop_cancels_directly():
    q = DownloadQueue()
    cancelled = []

    task = SimpleNamespace(done=lambda: False, cancel=lambda: cancelled.append("x"))
    loop = SimpleNamespace(is_running=lambda: False, call_soon_threadsafe=None)
    q._task = task
    q._loop = loop
    q._cancel_task_threadsafe()
    assert cancelled == ["x"]


def test_cancel_task_threadsafe_loop_none_cancels_directly():
    q = DownloadQueue()
    cancelled = []

    q._task = SimpleNamespace(done=lambda: False, cancel=lambda: cancelled.append("x"))
    q._loop = None
    q._cancel_task_threadsafe()
    assert cancelled == ["x"]


def test_cancel_task_threadsafe_task_none_is_noop():
    q = DownloadQueue()
    touched = []

    q._task = None
    q._loop = SimpleNamespace(
        is_running=lambda: touched.append("ran") or True,
        call_soon_threadsafe=lambda fn: touched.append("soon"),
    )
    q._cancel_task_threadsafe()
    assert touched == []


def test_cancel_task_threadsafe_done_task_is_noop():
    q = DownloadQueue()
    cancelled = []

    q._task = SimpleNamespace(done=lambda: True, cancel=lambda: cancelled.append("x"))
    q._loop = SimpleNamespace(
        is_running=lambda: True,
        call_soon_threadsafe=lambda fn: cancelled.append("soon"),
    )
    q._cancel_task_threadsafe()
    assert cancelled == []


def test_cancel_task_threadsafe_swallows_runtime_error():
    q = DownloadQueue()

    def raise_runtime(fn):
        raise RuntimeError("loop closed")

    q._task = SimpleNamespace(done=lambda: False, cancel=lambda: None)
    q._loop = SimpleNamespace(is_running=lambda: True, call_soon_threadsafe=raise_runtime)
    q._cancel_task_threadsafe()


def test_start_worker_outside_loop_logs_and_leaves_none(caplog):
    q = DownloadQueue()
    with caplog.at_level(logging.ERROR, logger="engine.download.queue"):
        q._start_worker()
    assert q._task is None
    assert q._loop is None
    assert any(
        "cannot start worker outside an event loop" in rec.getMessage()
        for rec in caplog.records
    )


def test_start_worker_creates_task_inside_loop():
    created = {}

    async def scenario():
        q = DownloadQueue()
        q._queue.append({"nom": "A"})
        import engine.download.worker as worker

        async def fake_traiter(item, qq):
            created["item"] = item

        worker.traiter_item, original = fake_traiter, worker.traiter_item
        try:
            q._start_worker()
            assert q._task is not None
            assert q._loop is asyncio.get_running_loop()
            await q._task
        finally:
            worker.traiter_item = original

    asyncio.run(scenario())
    assert created["item"] == {"nom": "A"}


def _fake_store(queue_items, history_items, current_item):
    return SimpleNamespace(
        load_queue=lambda: list(queue_items),
        load_history=lambda: list(history_items),
        load_current=lambda: current_item,
    )


def test_restore_empty_history_does_not_clobber_inmemory_history():
    q = DownloadQueue()
    q._history = [{"titre": "kept"}]
    q._store = _fake_store([{"nom": "A"}], [], None)
    q.restore()
    assert q._history == [{"titre": "kept"}]
    assert list(q._queue) == [{"nom": "A"}]


def test_restore_populates_history_when_present():
    q = DownloadQueue()
    q._history = [{"titre": "old"}]
    q._store = _fake_store([], [{"titre": "new"}], None)
    q.restore()
    assert q._history == [{"titre": "new"}]


def test_subscribe_appends_listener_invoked_on_emit():
    q = DownloadQueue()
    seen = []
    q.subscribe(lambda ev, data: seen.append((ev, data)))
    q.subscribe(lambda ev, data: seen.append(("second", ev)))
    q.emit("evt", {"k": 1})
    assert ("evt", {"k": 1}) in seen
    assert ("second", "evt") in seen


def test_emit_wraps_non_dict_into_value_key():
    q = DownloadQueue()
    seen = []
    q.subscribe(lambda ev, data: seen.append(data))
    q.emit("evt", [1, 2, 3])
    assert seen == [{"value": [1, 2, 3]}]


def test_emit_swallows_listener_exception_and_calls_remaining():
    q = DownloadQueue()
    good = []

    def bad(ev, data):
        raise RuntimeError("boom")

    q.subscribe(bad)
    q.subscribe(lambda ev, data: good.append((ev, data)))
    q.emit("evt", {"x": 1})
    assert good == [("evt", {"x": 1})]
