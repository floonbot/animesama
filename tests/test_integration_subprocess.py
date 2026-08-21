"""Gated real-IO integration tests for the streaming-subprocess code paths.

Marked ``integration`` so the default deterministic suite skips them
(``addopts = -m 'not integration'``). Run explicitly with::

    pytest -m integration

These complement ``test_integration_ffmpeg.py`` (which only asserts the happy
path produces an mp4): here we target the *streaming* lines specifically — the
real ``for ligne in proc.stderr`` progress loop with its time-gated callback,
the background ``_lire_stdout`` thread that parses real ``-progress pipe:1``
output, and (when the executables are present) the real yt-dlp / N_m3u8DL-RE
runs that the deterministic suite can only fake.
"""

import os
import re
import shutil
import subprocess
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from engine.download.methods import _proc_registry, ffmpeg_engine

pytestmark = pytest.mark.integration


def _have(exe: str) -> bool:
    return shutil.which(exe) is not None


class _SlowHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path.endswith(".ts"):
            time.sleep(0.35)
        return super().do_GET()


@pytest.fixture(autouse=True)
def _snapshot_globals(monkeypatch):
    saved_taille = ffmpeg_engine.TAILLE_MIN_FICHIER
    with _proc_registry._lock:
        saved_actifs = set(_proc_registry._actifs)
        saved_cancel = _proc_registry._cancel_en_cours
    yield
    ffmpeg_engine.TAILLE_MIN_FICHIER = saved_taille
    with _proc_registry._lock:
        _proc_registry._actifs.clear()
        _proc_registry._actifs.update(saved_actifs)
        _proc_registry._cancel_en_cours = saved_cancel


def _build_hls(src_dir, duration=6):
    src_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"testsrc=duration={duration}:size=320x240:rate=25",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "25",
                "-f", "hls", "-hls_time", "1", "-hls_playlist_type", "vod",
                str(src_dir / "index.m3u8"),
            ],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"ffmpeg cannot produce the HLS fixture (no libx264?): {e}")
    return src_dir / "index.m3u8"


def _serve(directory):
    handler = partial(_SlowHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


@pytest.mark.skipif(not _have("ffmpeg"), reason="ffmpeg not on PATH")
def test_ffmpeg_real_progress_streaming(tmp_path, monkeypatch):
    src = tmp_path / "src"
    playlist = _build_hls(src)
    assert playlist.exists()
    assert sum(1 for p in src.iterdir() if p.suffix == ".ts") >= 3

    server, port = _serve(src)
    try:
        monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 512)
        out_dir = tmp_path / "out"
        progress: list[tuple[float, str]] = []

        result = ffmpeg_engine.ffmpeg_download(
            f"http://127.0.0.1:{port}/index.m3u8",
            str(out_dir),
            "ep_stream",
            callback=lambda pct, msg: progress.append((pct, msg)),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result is not None, "real ffmpeg HLS download returned None"
    assert result.endswith("ep_stream.mp4")
    assert os.path.exists(result)
    assert os.path.getsize(result) > 512

    assert progress and progress[0][0] == 0.0
    assert progress[0][1].startswith("\U0001f534")

    ffmpeg_msgs = [msg for _pct, msg in progress if msg.startswith("[ffmpeg]")]
    assert ffmpeg_msgs, (
        "the real stderr streaming loop never emitted a [ffmpeg] progress line"
    )

    assert any(re.search(r"00:00:\d\d", msg) for msg in ffmpeg_msgs), (
        "real -progress streaming did not yield a HH:MM:SS time component"
    )

    assert progress[-1] == (100.0, "✅ ffmpeg terminé !")


@pytest.mark.skipif(not _have("ffmpeg"), reason="ffmpeg not on PATH")
def test_ffmpeg_real_cancel_during_streaming(tmp_path, monkeypatch):
    src = tmp_path / "src_cancel"
    _build_hls(src)
    server, port = _serve(src)

    cancelled = [False]

    def _cb(_pct, _msg):
        cancelled[0] = True

    try:
        monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 512)
        out_dir = tmp_path / "out_cancel"
        from engine.domain.exceptions import DownloadCancelled

        with pytest.raises(DownloadCancelled):
            ffmpeg_engine.ffmpeg_download(
                f"http://127.0.0.1:{port}/index.m3u8",
                str(out_dir),
                "ep_cancel",
                cancelled=cancelled,
                callback=_cb,
            )
    finally:
        server.shutdown()
        server.server_close()

    assert cancelled[0] is True


@pytest.mark.skipif(not _have("yt-dlp"), reason="yt-dlp not on PATH")
def test_ytdlp_real_streaming_download(tmp_path):
    from engine.download.methods import ytdlp_engine

    saved = ytdlp_engine.TAILLE_MIN_FICHIER
    ffmpeg_src = tmp_path / "yt_src"
    ffmpeg_src.mkdir()
    media = ffmpeg_src / "clip.mp4"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "testsrc=duration=3:size=320x240:rate=25",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(media),
            ],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"ffmpeg cannot produce the mp4 fixture: {e}")

    server, port = _serve(ffmpeg_src)
    try:
        ytdlp_engine.TAILLE_MIN_FICHIER = 512
        out_dir = tmp_path / "yt_out"
        progress: list[tuple[float, str]] = []
        result = ytdlp_engine.ytdlp_download(
            f"http://127.0.0.1:{port}/clip.mp4",
            str(out_dir),
            "yt_ep",
            callback=lambda pct, msg: progress.append((pct, msg)),
        )
    finally:
        ytdlp_engine.TAILLE_MIN_FICHIER = saved
        server.shutdown()
        server.server_close()

    assert result is not None, "real yt-dlp download returned None"
    assert os.path.exists(result)
    assert progress and progress[0][0] == 0.0
    assert any(msg.startswith("[yt-dlp]") or "yt-dlp" in msg for _pct, msg in progress)


@pytest.mark.skipif(
    not _have("N_m3u8DL-RE"), reason="N_m3u8DL-RE not on PATH"
)
def test_nm3u8dl_real_streaming_download(tmp_path, monkeypatch):
    from engine.download.methods import nm3u8dl

    src = tmp_path / "nm_src"
    _build_hls(src, duration=4)
    server, port = _serve(src)

    monkeypatch.setattr(nm3u8dl, "TAILLE_MIN_FICHIER", 512)

    try:
        out_dir = tmp_path / "nm_out"
        progress: list[tuple[float, str]] = []
        result = nm3u8dl.nm3u8dl_download(
            f"http://127.0.0.1:{port}/index.m3u8",
            str(out_dir),
            "nm_ep",
            callback=lambda pct, msg: progress.append((pct, msg)),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result is not None, "real N_m3u8DL-RE download returned None"
    assert os.path.exists(result)
    assert progress
