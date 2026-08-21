"""Regressions for the 3rd-sweep hardening batch.

- anime_done (integer counts) triggers a library refresh on a mixed batch.
- DiskCache.get survives a corrupt (non-numeric timestamp) entry.
- shutdown_covers clears the in-flight set (no permanent leak on cancel).
- ffmpeg out_time sub-second fraction is parsed.
- the parallel interception path honours + resets the per-host circuit breaker.
"""

import asyncio
from unittest.mock import Mock

import pytest

from engine.utils.circuit_breaker import CircuitState


def _wire_refresh(monkeypatch):
    import web.api.routes.sse as sse_mod
    from engine.library import scanner, updates

    inval_lib = Mock()
    inval_upd = Mock()
    monkeypatch.setattr(scanner, "invalider_cache_librairie", inval_lib)
    monkeypatch.setattr(updates, "invalider_cache_updates", inval_upd)
    return sse_mod, inval_lib, inval_upd


def test_anime_done_mixed_batch_refreshes(monkeypatch):
    sse_mod, inval_lib, inval_upd = _wire_refresh(monkeypatch)
    sse_mod._refresh_library_on_success("anime_done", {"succes": 2, "skipped": 1, "echoues": 0})
    inval_lib.assert_called_once()
    inval_upd.assert_called_once()


def test_anime_done_all_skipped_no_refresh(monkeypatch):
    sse_mod, inval_lib, inval_upd = _wire_refresh(monkeypatch)
    sse_mod._refresh_library_on_success("anime_done", {"succes": 0, "skipped": 3})
    inval_lib.assert_not_called()
    inval_upd.assert_not_called()


def test_episode_done_gating_unchanged(monkeypatch):
    sse_mod, inval_lib, _ = _wire_refresh(monkeypatch)
    sse_mod._refresh_library_on_success("episode_done", {"succes": True, "skipped": True})
    inval_lib.assert_not_called()
    sse_mod._refresh_library_on_success("episode_done", {"succes": True, "skipped": False})
    inval_lib.assert_called_once()


def test_disk_cache_get_survives_corrupt_timestamp(tmp_path, monkeypatch):
    import sqlite3

    from engine.cache import disk_cache as dc_mod
    from engine.cache.disk_cache import DiskCache

    monkeypatch.setattr(dc_mod, "DATA_DIR", tmp_path)
    dc = DiskCache("t_corrupt", 100)
    dc.set("good", "ok")

    conn = sqlite3.connect(str(tmp_path / "cache" / "t_corrupt.db"))
    conn.execute(
        "INSERT OR REPLACE INTO cache (key, ts, payload) VALUES ('bad', ?, ?)",
        ("not-a-number", '"v"'),
    )
    conn.commit()
    conn.close()

    assert dc.get("bad") is None
    assert dc.get("good") == "ok"


def test_shutdown_covers_clears_inflight(monkeypatch):
    from engine.cache import cover_images

    class _FakeExec:
        def shutdown(self, **k):
            return None

    monkeypatch.setattr(cover_images, "_executor", _FakeExec())
    cover_images._inflight.add("http://x/cover.jpg")
    try:
        cover_images.shutdown_covers()
        assert "http://x/cover.jpg" not in cover_images._inflight
    finally:
        cover_images._inflight.discard("http://x/cover.jpg")


def test_ffmpeg_out_time_subsecond_parsed():
    from engine.download.methods._ffmpeg_parsing import ProgressState, parse_progress_line

    st = ProgressState()
    parse_progress_line("out_time=00:00:07.500000", st)
    assert st.out_time_s == 7.5

    st2 = ProgressState()
    parse_progress_line("out_time=01:02:03", st2)
    assert st2.out_time_s == 3723.0


@pytest.fixture
def _clear_breakers():
    from engine.download import _host_breakers as hb

    hb._breakers.clear()
    yield hb
    hb._breakers.clear()


def test_essai_parallele_skips_open_host(monkeypatch, _clear_breakers):
    from engine.download import pipeline

    hb = _clear_breakers
    br = hb.get_breaker("dead.example")
    for _ in range(hb._FAILURE_THRESHOLD):
        br._on_failure(Exception("x"))
    assert br.state == CircuitState.OPEN

    called = {"n": 0}

    async def fake_par(lecteurs, timeout, on_win):
        called["n"] += 1
        return None

    monkeypatch.setattr(
        "engine.download.interceptor.intercepter_lecteurs_parallele", fake_par
    )
    res = asyncio.run(
        pipeline._essai_parallele([{"src": "https://dead.example/e", "host": "dead.example"}])
    )
    assert res is None
    assert called["n"] == 0


def test_essai_parallele_win_resets_breaker(monkeypatch, _clear_breakers):
    from engine.download import pipeline

    hb = _clear_breakers
    br = hb.get_breaker("flaky.example")
    br._on_failure(Exception("x"))
    assert br._failures == 1

    async def fake_par(lecteurs, timeout, on_win):
        on_win("https://flaky.example/e")
        return {"url": "https://cdn/v.m3u8", "headers": {}}

    monkeypatch.setattr(
        "engine.download.interceptor.intercepter_lecteurs_parallele", fake_par
    )
    res = asyncio.run(
        pipeline._essai_parallele([{"src": "https://flaky.example/e", "host": "flaky.example"}])
    )
    assert res == {"url": "https://cdn/v.m3u8", "headers": {}}
    assert hb.get_breaker("flaky.example")._failures == 0
