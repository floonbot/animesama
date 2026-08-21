import logging

from engine.config import logging_setup as ls
from engine.observability.context import (
    get_task_id,
    reset_task_id,
    set_task_id,
    task_context,
)


def _record(msg="hello"):
    return logging.LogRecord(
        "engine.download.pipeline", logging.INFO, __file__, 1, msg, (), None
    )


def test_task_context_sets_and_resets():
    assert get_task_id() == ""
    with task_context("abc123"):
        assert get_task_id() == "abc123"
    assert get_task_id() == ""


def test_task_context_restores_previous_on_nesting():
    with task_context("outer1"):
        with task_context("inner2"):
            assert get_task_id() == "inner2"
        assert get_task_id() == "outer1"
    assert get_task_id() == ""


def test_set_reset_task_id_roundtrip():
    token = set_task_id("zz9988")
    assert get_task_id() == "zz9988"
    reset_task_id(token)
    assert get_task_id() == ""


def test_formatter_includes_task_id_when_set():
    out_no = ls.CleanFormatter().format(_record())
    assert "[deadbe]" not in out_no
    with task_context("deadbe"):
        out_yes = ls.CleanFormatter().format(_record())
    assert "[deadbe]" in out_yes
    assert "hello" in out_yes


def test_formatter_omits_brackets_when_unset():
    out = ls.CleanFormatter().format(_record())
    assert "[" not in out


def test_logs_from_any_module_carry_id_within_task_context():
    import io

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(ls.CleanFormatter())
    for name in ("engine.download._rate_limiter", "engine.download._helpers"):
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        try:
            with task_context("ctx777"):
                lg.warning("message depuis %s", name)
        finally:
            lg.removeHandler(handler)
    out = buf.getvalue()
    assert out.count("[ctx777]") == 2
    assert "message depuis engine.download._rate_limiter" in out
    assert "message depuis engine.download._helpers" in out


def test_watchdog_thread_inherits_task_id():
    import threading

    from engine.download import _engine_utils as eu

    seen = {}
    done = threading.Event()

    class _FakeProc:
        def poll(self):
            seen["tid"] = get_task_id()
            done.set()
            raise RuntimeError("stop watchdog")

    with task_context("wd1234"):
        stop = eu.spawn_proc_watchdog(_FakeProc(), None, 5.0)

    assert done.wait(2.0)
    stop.set()
    assert seen["tid"] == "wd1234"
