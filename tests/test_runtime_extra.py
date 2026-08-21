import asyncio
from types import SimpleNamespace

import pytest

from engine.download import _runtime as runtime
from engine.download.queue import CancelToken
from engine.observability.metrics import metrics


@pytest.fixture
def reset_metrics():
    metrics.reset()
    yield metrics
    metrics.reset()


def _named(name, result):
    def fn(*a):
        if isinstance(result, Exception):
            raise result
        return result

    fn.__name__ = name
    return fn


def test_run_in_pool_records_engine_success_metrics(reset_metrics):
    out = asyncio.run(runtime._run_in_pool(_named("ytdlp_download", "stream-handle")))
    assert out == "stream-handle"
    snap = reset_metrics.snapshot()
    assert snap.get("download_ytdlp_ok") == 1
    assert snap.get("download_ytdlp_attempts") == 1


def test_run_in_pool_records_engine_failure_metric(reset_metrics):
    out = asyncio.run(runtime._run_in_pool(_named("ffmpeg_download", None)))
    assert out is None
    snap = reset_metrics.snapshot()
    assert snap.get("download_ffmpeg_fail") == 1
    assert snap.get("download_ffmpeg_attempts") == 1


def test_run_in_pool_non_engine_records_no_download_metrics(reset_metrics):
    out = asyncio.run(runtime._run_in_pool(_named("some_helper", "value")))
    assert out == "value"
    snap = reset_metrics.snapshot()
    assert not any(k.startswith("download_") for k in snap)


def test_armer_token_annulation_sets_during_sleep_then_clears(monkeypatch):
    tok = CancelToken()
    captured = []

    async def fake_sleep(_):
        captured.append(tok.is_cancelled())

    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)
    asyncio.run(runtime._armer_token_annulation(SimpleNamespace(_cancelled=tok)))
    assert captured == [True]
    assert tok.is_cancelled() is False


def test_armer_token_annulation_legacy_list_token(monkeypatch):
    tok = [False]
    captured = []

    async def fake_sleep(_):
        captured.append(tok[0])

    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)
    asyncio.run(runtime._armer_token_annulation(SimpleNamespace(_cancelled=tok)))
    assert captured == [True]
    assert tok[0] is False


def test_armer_token_annulation_none_token_is_noop(monkeypatch):
    async def boom(_):
        raise AssertionError("sleep must not run when there is no token")

    monkeypatch.setattr(runtime.asyncio, "sleep", boom)
    asyncio.run(runtime._armer_token_annulation(SimpleNamespace()))


def test_signaler_annulation_engine_kills_processes_and_arms_token(monkeypatch):
    killed = []
    monkeypatch.setattr(
        "engine.download.methods._proc_registry.kill_all_processes",
        lambda: killed.append(True),
    )

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)
    tok = CancelToken()
    asyncio.run(runtime._signaler_annulation_engine(SimpleNamespace(_cancelled=tok)))
    assert killed == [True]
    assert tok.is_cancelled() is False
