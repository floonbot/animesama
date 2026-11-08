"""Regression: a download that recovers from a transient 403/429 must be kept.

yt-dlp logs a transient `HTTP Error 403` on a fragment, then retries
(`--fragment-retries`/`--retries`) and finishes with returncode 0 and a valid
file. Previously the sticky `got_403` flag raised RateLimitError *before*
validating the output, discarding the completed download. The fix validates the
output first and only raises RateLimitError when no valid file was produced.
"""

import threading

from engine.download.methods import ytdlp_engine


class _Iter:
    def __init__(self, items):
        self._items = list(items)
        self._i = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._items):
            raise StopIteration
        item = self._items[self._i]
        self._i += 1
        return item

    def close(self):
        return None


class _Proc:
    def __init__(self, stdout_lines, returncode=0):
        self.returncode = returncode
        self.pid = 4321
        self.stdout = _Iter(stdout_lines)
        self.stderr = None

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        return None

    def terminate(self):
        return None


class _Factory:
    def __init__(self, proc):
        self.proc = proc

    def __call__(self, cmd, *args, **kwargs):
        return self.proc


def _neutralize(monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "720"})


def test_transient_403_then_success_keeps_file(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 4096)

    factory = _Factory(_Proc(
        stdout_lines=[
            "ERROR: unable to download: HTTP Error 403: Forbidden",
            "[download]  50.0% of ~100.00MiB at 5.00MiB/s ETA 00:30",
            "[download] 100% of 100.00MiB",
        ],
        returncode=0,
    ))
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: str(final))
    _neutralize(monkeypatch)

    res = ytdlp_engine.ytdlp_download("http://host.example/video", str(tmp_path), "ep")
    assert res == str(final)


def test_403_without_file_still_raises_ratelimit(tmp_path, monkeypatch):
    factory = _Factory(_Proc(
        stdout_lines=["ERROR: unable to download: HTTP Error 403: Forbidden"],
        returncode=0,
    ))
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: None)
    _neutralize(monkeypatch)

    import pytest
    with pytest.raises(ytdlp_engine.RateLimitError) as exc:
        ytdlp_engine.ytdlp_download("http://host.example/video", str(tmp_path), "ep")
    assert exc.value.domain == "host.example"
