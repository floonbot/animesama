import asyncio
from types import SimpleNamespace

import pytest

from engine.download import _runtime as runtime
from engine.observability.metrics import metrics


@pytest.fixture(autouse=True)
def reset_metrics():
    metrics.reset()
    yield metrics
    metrics.reset()


def _named(name, fn):
    fn.__name__ = name
    return fn


def test_run_in_pool_existing_file_adds_bytes_total(tmp_path):
    payload = b"abcde-bytes"
    target = tmp_path / "video.mp4"
    target.write_bytes(payload)

    def body(*a):
        return str(target)

    out = asyncio.run(runtime._run_in_pool(_named("nm3u8dl_download", body)))

    assert out == str(target)
    snap = metrics.snapshot()
    assert snap.get("download_nm3u8dl_ok") == 1
    assert snap.get("download_nm3u8dl_attempts") == 1
    assert snap.get("bytes_total") == len(payload)


def test_run_in_pool_records_per_engine_bytes_and_latency(tmp_path):
    payload = b"0123456789"
    target = tmp_path / "v.mp4"
    target.write_bytes(payload)

    def body(*a):
        return str(target)

    asyncio.run(runtime._run_in_pool(_named("nm3u8dl_download", body)))

    snap = metrics.snapshot()
    assert snap.get("download_nm3u8dl_bytes") == len(payload)
    assert metrics.percentiles("lat_nm3u8dl_s")["count"] == 1


def test_run_in_pool_observes_latency_even_on_failure():
    def body(*a):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        asyncio.run(runtime._run_in_pool(_named("ffmpeg_download", body)))

    assert metrics.percentiles("lat_ffmpeg_s")["count"] == 1
    assert "download_ffmpeg_bytes" not in metrics.snapshot()


def test_run_in_pool_propagates_task_id_into_thread():
    from engine.observability.context import get_task_id, task_context

    seen = {}

    def body(*a):
        seen["tid"] = get_task_id()
        return "x"

    with task_context("ep1234"):
        asyncio.run(runtime._run_in_pool(_named("ytdlp_download", body)))

    assert seen["tid"] == "ep1234"


def test_run_in_pool_success_non_path_string_no_bytes_total(tmp_path):
    missing = str(tmp_path / "does-not-exist.mp4")

    def body(*a):
        return missing

    out = asyncio.run(runtime._run_in_pool(_named("nm3u8dl_download", body)))

    assert out == missing
    snap = metrics.snapshot()
    assert snap.get("download_nm3u8dl_ok") == 1
    assert "bytes_total" not in snap


def test_run_in_pool_success_non_str_result_no_bytes_total():
    def body(*a):
        return 7

    out = asyncio.run(runtime._run_in_pool(_named("ytdlp_download", body)))

    assert out == 7
    snap = metrics.snapshot()
    assert snap.get("download_ytdlp_ok") == 1
    assert "bytes_total" not in snap


def test_run_in_pool_getsize_oserror_swallowed_no_bytes_total(monkeypatch, tmp_path):
    target = tmp_path / "v.mp4"
    target.write_bytes(b"xy")

    def boom_getsize(_p):
        raise OSError("stat failed")

    monkeypatch.setattr(runtime.os.path, "getsize", boom_getsize)

    def body(*a):
        return str(target)

    out = asyncio.run(runtime._run_in_pool(_named("nm3u8dl_download", body)))

    assert out == str(target)
    snap = metrics.snapshot()
    assert snap.get("download_nm3u8dl_ok") == 1
    assert "bytes_total" not in snap


def test_run_in_pool_metrics_failure_is_swallowed_and_result_returned(monkeypatch, tmp_path):
    target = tmp_path / "ok.mp4"
    target.write_bytes(b"zzz")
    calls = []

    class _BoomMetrics:
        def incr(self, *a, **k):
            calls.append(a)
            raise RuntimeError("metrics down")

    import engine.observability.metrics as metrics_mod

    monkeypatch.setattr(metrics_mod, "metrics", _BoomMetrics())

    def body(*a):
        return str(target)

    out = asyncio.run(runtime._run_in_pool(_named("nm3u8dl_download", body)))

    assert out == str(target)
    assert calls and calls[0][0] == "download_nm3u8dl_ms"
    assert metrics.snapshot() == {}


def test_run_in_pool_engine_exception_records_fail_and_propagates():
    def body(*a):
        raise RuntimeError("engine exploded")

    with pytest.raises(RuntimeError, match="engine exploded"):
        asyncio.run(runtime._run_in_pool(_named("ffmpeg_download", body)))

    snap = metrics.snapshot()
    assert snap.get("download_ffmpeg_fail") == 1
    assert snap.get("download_ffmpeg_attempts") == 1
    assert "download_ffmpeg_ok" not in snap


def test_historique_ajouter_delegates_to_append(monkeypatch):
    captured = []
    monkeypatch.setattr(
        runtime, "_historique_append", lambda q, entree: captured.append((q, entree))
    )
    sentinel = SimpleNamespace()

    runtime._historique_ajouter(sentinel, "Naruto", "VF", succes=4, echoues=2, skipped=1)

    assert captured == [(
        sentinel,
        {"titre": "Naruto", "langue": "VF", "succes": 4, "echoues": 2, "skipped": 1},
    )]


def test_historique_ajouter_defaults_zero(monkeypatch):
    captured = []
    monkeypatch.setattr(
        runtime, "_historique_append", lambda q, entree: captured.append(entree)
    )

    runtime._historique_ajouter(SimpleNamespace(), "T", "VOSTFR")

    assert captured == [
        {"titre": "T", "langue": "VOSTFR", "succes": 0, "echoues": 0, "skipped": 0}
    ]


def test_safe_emit_forwards_event_and_data():
    seen = []

    queue = SimpleNamespace(emit=lambda ev, data: seen.append((ev, data)))
    runtime._safe_emit(queue, "episode_done", {"nom": "X"})

    assert seen == [("episode_done", {"nom": "X"})]


def test_safe_emit_swallows_raising_emit():
    def boom(ev, data):
        raise ValueError("emit broke")

    queue = SimpleNamespace(emit=boom)

    runtime._safe_emit(queue, "dl_annule", {"nom": "Y"})


def test_tuer_sous_process_moteur_swallows_kill_failure(monkeypatch):
    called = []

    def boom():
        called.append(True)
        raise RuntimeError("cannot kill")

    monkeypatch.setattr(
        "engine.download.methods._proc_registry.kill_all_processes", boom
    )

    runtime._tuer_sous_process_moteur()

    assert called == [True]


def test_tuer_sous_process_moteur_calls_kill_all(monkeypatch):
    called = []
    monkeypatch.setattr(
        "engine.download.methods._proc_registry.kill_all_processes",
        lambda: called.append(True),
    )

    runtime._tuer_sous_process_moteur()

    assert called == [True]


def test_signaler_annulation_engine_swallows_kill_failure(monkeypatch):
    monkeypatch.setattr(
        "engine.download.methods._proc_registry.kill_all_processes",
        lambda: (_ for _ in ()).throw(RuntimeError("kill failed")),
    )

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)

    asyncio.run(runtime._signaler_annulation_engine(SimpleNamespace(_cancelled=None)))


def test_shutdown_cancels_futures_without_waiting(monkeypatch):
    recorded = {}

    fake_executor = SimpleNamespace(
        shutdown=lambda **kw: recorded.update(kw)
    )
    monkeypatch.setattr(runtime, "_executor", fake_executor)

    runtime.shutdown()

    assert recorded == {"wait": False, "cancel_futures": True}
