import os
import time

import engine.config.settings as settings_mod
import engine.download.methods.nm3u8dl as nm3u8dl


class _FakeStop:
    def __init__(self):
        self.is_set_calls = 0
        self.wait_calls = []

    def is_set(self):
        self.is_set_calls += 1
        return False

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return True


class _FakeCompleted:
    def __init__(self, returncode):
        self.returncode = returncode


class _FakeRemuxProc:
    def __init__(self, returncode, out_local=None, out_bytes=b"REMUXED"):
        self._rc = returncode
        self._out = out_local
        self._out_bytes = out_bytes

    def wait(self, timeout=None):
        if self._out is not None:
            with open(self._out, "wb") as f:
                f.write(self._out_bytes)
        return self._rc

    def poll(self):
        return None

    def kill(self):
        pass


def _make_dir_with_mtime(parent, name, mtime=None):
    full = os.path.join(str(parent), name)
    os.makedirs(full, exist_ok=True)
    if mtime is not None:
        os.utime(full, (mtime, mtime))
    return full


def test_purge_removes_only_stale_tmp_dirs(tmp_path, monkeypatch):
    old_ts = time.time() - 8 * 86400
    stale = _make_dir_with_mtime(tmp_path, "_tmp_old", old_ts)
    fresh = _make_dir_with_mtime(tmp_path, "_tmp_new")
    keep = _make_dir_with_mtime(tmp_path, "KeepMe")

    monkeypatch.setattr(settings_mod, "get_downloads_dir", lambda: tmp_path)

    removed = nm3u8dl.purge_stale_tmp_dirs(max_age_s=3600)

    assert removed == 1
    assert not os.path.exists(stale)
    assert os.path.isdir(fresh)
    assert os.path.isdir(keep)


def test_purge_returns_zero_when_downloads_dir_raises(tmp_path, monkeypatch):
    def _boom():
        raise RuntimeError("no downloads dir")

    monkeypatch.setattr(settings_mod, "get_downloads_dir", _boom)

    assert nm3u8dl.purge_stale_tmp_dirs(max_age_s=3600) == 0


def test_monitor_tmp_one_iteration_reports_progress(tmp_path):
    tmp_dir = tmp_path / "_tmp_seg"
    tmp_dir.mkdir()
    for i in range(3):
        (tmp_dir / f"seg{i}.ts").write_bytes(b"x" * 100)

    now = time.time()
    state = {
        "total_segs": 6,
        "start_time": now - 10,
        "last_size": 0,
        "last_time": now - 10,
        "speed_bps": 0.0,
        "phase": "downloading",
    }
    calls = []

    def callback(pct, ligne):
        calls.append((pct, ligne))

    stop = _FakeStop()
    nm3u8dl._monitor_tmp(str(tmp_dir), state, stop, callback)

    assert len(calls) == 1
    pct, ligne = calls[0]
    assert pct == 50.0
    assert "3/6 segments" in ligne


def test_monitor_tmp_no_callback_when_phase_not_downloading(tmp_path):
    tmp_dir = tmp_path / "_tmp_seg"
    tmp_dir.mkdir()
    for i in range(3):
        (tmp_dir / f"seg{i}.ts").write_bytes(b"x" * 100)

    now = time.time()
    state = {
        "total_segs": 6,
        "start_time": now - 10,
        "last_size": 0,
        "last_time": now - 10,
        "speed_bps": 0.0,
        "phase": "init",
    }
    calls = []

    def callback(pct, ligne):
        calls.append((pct, ligne))

    stop = _FakeStop()
    nm3u8dl._monitor_tmp(str(tmp_dir), state, stop, callback)

    assert calls == []


def test_remux_fix_no_ffmpeg_returns_chemin_unchanged(tmp_path, monkeypatch):
    chemin = tmp_path / "video.mp4"
    chemin.write_bytes(b"ORIGINAL")

    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda _name: None)

    calls = []

    def callback(pct, ligne):
        calls.append((pct, ligne))

    monkeypatch.setattr(nm3u8dl, "_find_ffmpeg", lambda: None)

    result = nm3u8dl._remux_fix(str(chemin), callback)

    assert result == str(chemin)
    assert chemin.read_bytes() == b"ORIGINAL"
    assert calls == []


def test_remux_fix_success_replaces_file(tmp_path, monkeypatch):
    chemin = tmp_path / "video.mp4"
    chemin.write_bytes(b"ORIGINAL")

    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda _name: "ffmpeg")

    def fake_popen(cmd, *a, **kwargs):
        out_local = cmd[-1]
        assert os.path.basename(out_local).startswith("out_")
        return _FakeRemuxProc(0, out_local=out_local)

    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", fake_popen)

    calls = []

    def callback(pct, ligne):
        calls.append((pct, ligne))

    result = nm3u8dl._remux_fix(str(chemin), callback)

    assert result == str(chemin)
    assert chemin.read_bytes() == b"REMUXED"
    assert len(calls) == 1
    assert calls[0][0] == 99.0


def test_remux_fix_nonzero_returncode_keeps_original(tmp_path, monkeypatch):
    chemin = tmp_path / "video.mp4"
    chemin.write_bytes(b"ORIGINAL")

    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda _name: "ffmpeg")

    def fake_popen(cmd, *a, **kwargs):
        return _FakeRemuxProc(1, out_local=cmd[-1])

    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", fake_popen)

    result = nm3u8dl._remux_fix(str(chemin), None)

    assert result == str(chemin)
    assert chemin.read_bytes() == b"ORIGINAL"
