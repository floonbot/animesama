import asyncio

import pytest

import web.api.app as app_mod
from engine.download.queue import DownloadQueue
from engine.observability.context import get_task_id, reset_task_id, set_task_id
from engine.observability.metrics import metrics


def test_request_context_sets_and_resets_task_id():
    seen = {}

    async def inner(scope, receive, send):
        seen["tid"] = get_task_id()

    mw = app_mod.RequestContext(inner)

    async def recv():
        return {"type": "http.request"}

    async def send(_m):
        return None

    asyncio.run(mw({"type": "http"}, recv, send))
    assert seen["tid"]
    assert len(seen["tid"]) == 6
    assert get_task_id() == ""


def test_request_context_passthrough_non_http():
    called = {}

    async def inner(scope, receive, send):
        called["tid"] = get_task_id()

    mw = app_mod.RequestContext(inner)
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert called["tid"] == ""


def _run_metrics_mw(path, status):
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = app_mod.RequestMetrics(inner)

    async def recv():
        return {"type": "http.request"}

    async def send(_m):
        return None

    asyncio.run(mw({"type": "http", "path": path}, recv, send))


def test_request_metrics_counts_api_5xx():
    metrics.reset()
    try:
        _run_metrics_mw("/api/x", 503)
        snap = metrics.snapshot()
        assert snap.get("http_requests_total") == 1
        assert snap.get("http_requests_5xx") == 1
        assert "http_requests_4xx" not in snap
    finally:
        metrics.reset()


def test_request_metrics_counts_api_4xx():
    metrics.reset()
    try:
        _run_metrics_mw("/api/x", 404)
        snap = metrics.snapshot()
        assert snap.get("http_requests_total") == 1
        assert snap.get("http_requests_4xx") == 1
        assert "http_requests_5xx" not in snap
    finally:
        metrics.reset()


def test_request_metrics_ignores_non_api_and_counts_2xx():
    metrics.reset()
    try:
        _run_metrics_mw("/index.html", 200)
        assert metrics.snapshot() == {}
        _run_metrics_mw("/api/ok", 200)
        snap = metrics.snapshot()
        assert snap.get("http_requests_total") == 1
        assert snap.get("http_requests_2xx") == 1
        assert "http_requests_4xx" not in snap
        assert "http_requests_5xx" not in snap
    finally:
        metrics.reset()


def test_request_metrics_counts_3xx():
    metrics.reset()
    try:
        _run_metrics_mw("/api/x", 304)
        snap = metrics.snapshot()
        assert snap.get("http_requests_total") == 1
        assert snap.get("http_requests_3xx") == 1
    finally:
        metrics.reset()


def test_request_metrics_diag_endpoints_bucketed_separately():
    metrics.reset()
    try:
        _run_metrics_mw("/api/health", 200)
        _run_metrics_mw("/api/metrics", 200)
        snap = metrics.snapshot()
        assert snap.get("http_requests_diag") == 2
        assert "http_requests_total" not in snap
        assert "http_requests_2xx" not in snap
    finally:
        metrics.reset()


def test_request_metrics_observes_latency_for_normal_requests():
    metrics.reset()
    try:
        _run_metrics_mw("/api/ok", 200)
        assert metrics.percentiles("lat_request_s").get("count") == 1
    finally:
        metrics.reset()


def test_request_metrics_media_bucketed_and_no_latency():
    metrics.reset()
    try:
        _run_metrics_mw("/api/events", 200)
        _run_metrics_mw("/api/anime/stream", 206)
        snap = metrics.snapshot()
        assert snap.get("http_requests_media") == 2
        assert "http_requests_total" not in snap
        assert "http_requests_2xx" not in snap
        assert metrics.percentiles("lat_request_s") == {}
    finally:
        metrics.reset()


def test_request_metrics_diag_has_no_latency():
    metrics.reset()
    try:
        _run_metrics_mw("/api/health", 200)
        assert metrics.percentiles("lat_request_s") == {}
        assert metrics.snapshot().get("http_requests_diag") == 1
    finally:
        metrics.reset()


def test_request_metrics_counts_unhandled_exception_as_5xx():
    metrics.reset()

    async def inner(scope, receive, send):
        raise RuntimeError("boom")

    mw = app_mod.RequestMetrics(inner)

    async def recv():
        return {"type": "http.request"}

    async def send(_m):
        return None

    async def run():
        with pytest.raises(RuntimeError):
            await mw({"type": "http", "path": "/api/x"}, recv, send)

    try:
        asyncio.run(run())
        snap = metrics.snapshot()
        assert snap.get("http_requests_total") == 1
        assert snap.get("http_requests_5xx") == 1
        total = snap.get("http_requests_total", 0)
        classes = sum(snap.get(f"http_requests_{c}", 0) for c in ("2xx", "3xx", "4xx", "5xx"))
        assert total == classes
    finally:
        metrics.reset()


def test_worker_run_baseline_not_inherited_from_request(monkeypatch):
    import engine.download.worker as worker_mod

    seen = {}

    async def fake_traiter(item, q):
        seen["tid"] = get_task_id()

    monkeypatch.setattr(worker_mod, "traiter_item", fake_traiter)
    q = DownloadQueue()
    q._queue.append({"episodes": [{"url": "u"}]})

    async def run_in_request_ctx():
        token = set_task_id("reqabc")
        try:
            await q._run()
        finally:
            reset_task_id(token)

    try:
        asyncio.run(run_in_request_ctx())
    finally:
        metrics.reset()
    assert seen["tid"] == ""
