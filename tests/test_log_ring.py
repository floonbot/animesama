import logging

from engine.observability.context import task_context
from engine.observability.log_ring import RingBufferHandler, log_ring


def _record(name, level, msg, args=None):
    return logging.LogRecord(name, level, __file__, 1, msg, args, None)


def test_emit_captures_structured_entry():
    h = RingBufferHandler(capacity=10)
    h.emit(_record("a.b", logging.INFO, "hello %s", ("world",)))
    snap = h.snapshot()
    assert len(snap) == 1
    e = snap[0]
    assert e["msg"] == "hello world"
    assert e["level"] == "INFO"
    assert e["logger"] == "a.b"
    assert set(e) >= {"ts", "level", "logger", "tid", "msg"}


def test_emit_records_task_id_when_set():
    h = RingBufferHandler(capacity=10)
    with task_context("ctx999"):
        h.emit(_record("a", logging.WARNING, "boom"))
    assert h.snapshot()[0]["tid"] == "ctx999"


def test_buffer_is_bounded():
    h = RingBufferHandler(capacity=5)
    for i in range(20):
        h.emit(_record("a", logging.INFO, f"m{i}"))
    snap = h.snapshot()
    assert len(snap) == 5
    assert snap[0]["msg"] == "m15"
    assert snap[-1]["msg"] == "m19"


def test_snapshot_limit_and_tid_filter():
    h = RingBufferHandler(capacity=50)
    with task_context("t1"):
        h.emit(_record("a", logging.INFO, "one"))
    h.emit(_record("a", logging.INFO, "two"))
    with task_context("t1"):
        h.emit(_record("a", logging.INFO, "three"))
    assert [e["msg"] for e in h.snapshot(tid="t1")] == ["one", "three"]
    assert [e["msg"] for e in h.snapshot(limit=1)] == ["three"]


def test_entry_includes_levelno():
    h = RingBufferHandler(capacity=5)
    h.emit(_record("a", logging.ERROR, "x"))
    assert h.snapshot()[0]["levelno"] == logging.ERROR


def test_snapshot_min_level_filter():
    h = RingBufferHandler(capacity=50)
    h.emit(_record("a", logging.INFO, "i"))
    h.emit(_record("a", logging.WARNING, "w"))
    h.emit(_record("a", logging.ERROR, "e"))
    assert [x["msg"] for x in h.snapshot(min_levelno=logging.WARNING)] == ["w", "e"]


def test_level_threshold_resolves_names():
    from engine.observability.log_ring import level_threshold

    assert level_threshold("WARNING") == logging.WARNING
    assert level_threshold("error") == logging.ERROR
    assert level_threshold("OK") == 25
    assert level_threshold("") == 0
    assert level_threshold("bogus") == 0


def test_snapshot_limit_zero_returns_empty():
    h = RingBufferHandler(capacity=5)
    for i in range(3):
        h.emit(_record("a", logging.INFO, f"m{i}"))
    assert h.snapshot(limit=0) == []
    assert [e["msg"] for e in h.snapshot(limit=2)] == ["m1", "m2"]


def test_clear_empties_buffer():
    h = RingBufferHandler(capacity=5)
    h.emit(_record("a", logging.INFO, "x"))
    h.clear()
    assert h.snapshot() == []


def test_module_singleton_is_a_handler():
    assert isinstance(log_ring, logging.Handler)


def test_emit_scrubs_unredacted_signed_url():
    h = RingBufferHandler(capacity=5)
    h.emit(_record("a", logging.WARNING, "stream https://h/v.m3u8?token=SECRET99&sig=z"))
    msg = h.snapshot()[0]["msg"]
    assert "SECRET99" not in msg
    assert "stream https://h/v.m3u8" in msg
