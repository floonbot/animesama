import logging

import pytest

from engine.observability.context import task_context
from engine.observability.log_ring import log_ring


@pytest.fixture(autouse=True)
def _isolate_ring():
    root = logging.getLogger()
    was_attached = log_ring in root.handlers
    if was_attached:
        root.removeHandler(log_ring)
    log_ring.clear()
    yield
    log_ring.clear()
    if was_attached and log_ring not in root.handlers:
        root.addHandler(log_ring)


def _emit(msg, tid="", level=logging.WARNING):
    rec = logging.LogRecord("test.logs", level, __file__, 1, msg, None, None)
    if tid:
        with task_context(tid):
            log_ring.emit(rec)
    else:
        log_ring.emit(rec)


def test_api_logs_returns_recent_entries(client):
    _emit("ping one")
    body = client.get("/api/logs").json()
    assert body["ok"] is True
    assert body["count"] == 1
    last = body["logs"][-1]
    assert last["msg"] == "ping one"
    assert set(last) >= {"ts", "level", "logger", "tid", "msg"}


def test_api_logs_limit_caps_results(client):
    for i in range(10):
        _emit(f"m{i}")
    body = client.get("/api/logs?limit=3").json()
    assert body["count"] == 3
    assert [e["msg"] for e in body["logs"]] == ["m7", "m8", "m9"]


def test_api_logs_tid_filter(client):
    _emit("tagged", tid="zz9")
    _emit("untagged")
    body = client.get("/api/logs?tid=zz9").json()
    assert [e["msg"] for e in body["logs"]] == ["tagged"]


def test_api_logs_level_filter(client):
    _emit("info one", level=logging.INFO)
    _emit("warn two", level=logging.WARNING)
    _emit("err three", level=logging.ERROR)
    body = client.get("/api/logs?level=WARNING").json()
    assert [e["msg"] for e in body["logs"]] == ["warn two", "err three"]


def test_api_logs_route_registered():
    from fastapi.testclient import TestClient

    from web.api.app import create_app

    c = TestClient(create_app(), base_url="http://localhost")
    assert c.get("/api/logs").status_code == 200
