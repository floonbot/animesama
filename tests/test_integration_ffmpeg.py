"""Gated real-IO integration test for the ffmpeg HLS download path.

Marked ``integration`` so the default fast/deterministic suite skips it
(``addopts = -m 'not integration'``). Run explicitly with::

    pytest -m integration

It generates a tiny real HLS stream with the system ffmpeg, serves it from a
local loopback HTTP server, and drives the engine's real ``ffmpeg_download``
(real subprocess, real watchdog) end to end — exactly the lines the
deterministic suite cannot cover honestly without a real process.
"""

import os
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from engine.download.methods import ffmpeg_engine

pytestmark = pytest.mark.integration


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def _have(exe: str) -> bool:
    return shutil.which(exe) is not None


@pytest.mark.skipif(not _have("ffmpeg"), reason="ffmpeg not on PATH")
def test_ffmpeg_download_real_hls_end_to_end(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "testsrc=duration=2:size=160x120:rate=15",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-f", "hls", "-hls_time", "1", "-hls_playlist_type", "vod",
                str(src / "index.m3u8"),
            ],
            check=True, capture_output=True, timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"ffmpeg cannot produce the HLS fixture (no libx264?): {e}")

    assert (src / "index.m3u8").exists()
    assert any(p.suffix == ".ts" for p in src.iterdir())

    handler = partial(_QuietHandler, directory=str(src))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 512)
        out_dir = tmp_path / "out"
        progress: list[tuple[float, str]] = []

        result = ffmpeg_engine.ffmpeg_download(
            f"http://127.0.0.1:{port}/index.m3u8",
            str(out_dir),
            "ep_real",
            callback=lambda pct, msg: progress.append((pct, msg)),
        )

        assert result is not None, "real ffmpeg HLS download returned None"
        assert result.endswith("ep_real.mp4")
        assert os.path.exists(result)
        assert os.path.getsize(result) > 512
    finally:
        server.shutdown()
        server.server_close()
