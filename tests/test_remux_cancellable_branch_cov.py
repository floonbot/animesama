"""Regression: the nm3u8dl remux step ran ffmpeg via subprocess.run without
registering the child, so a cancel could not terminate it (stray ffmpeg up to
REMUX_TIMEOUT). It now spawns via Popen + register_proc/unregister_proc (so the
normal cancel path — kill_all_processes — reaches it) and kills the child on
timeout.
"""

import subprocess
import tempfile

import engine.download.methods.nm3u8dl as nm3u8dl


def _wire(monkeypatch, tmp_path):
    workdir = tmp_path / "remux_work"
    workdir.mkdir()
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: "ffmpeg")
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(workdir))
    monkeypatch.setattr(nm3u8dl.shutil, "copy2", lambda s, d: None)
    monkeypatch.setattr(nm3u8dl.shutil, "rmtree", lambda p, **k: None)


def test_remux_registers_and_unregisters_child(monkeypatch, tmp_path):
    chemin = tmp_path / "ep.mp4"
    chemin.write_bytes(b"z" * 64)
    _wire(monkeypatch, tmp_path)

    class _P:
        def wait(self, timeout=None):
            return 1

        def poll(self):
            return None

        def kill(self):
            pass

    the_proc = _P()
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", lambda cmd, *a, **k: the_proc)

    registered, unregistered = [], []
    monkeypatch.setattr(nm3u8dl, "register_proc", lambda p: registered.append(p))
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda p: unregistered.append(p))

    res = nm3u8dl._remux_fix(str(chemin))

    assert res == str(chemin)
    assert registered == [the_proc]
    assert unregistered == [the_proc]


def test_remux_timeout_kills_child_and_keeps_original(monkeypatch, tmp_path):
    chemin = tmp_path / "ep.mp4"
    chemin.write_bytes(b"ORIGINAL")
    _wire(monkeypatch, tmp_path)

    class _P:
        def __init__(self):
            self.killed = False

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout or 300)
            return -9

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    the_proc = _P()
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", lambda cmd, *a, **k: the_proc)
    monkeypatch.setattr(nm3u8dl, "register_proc", lambda p: None)
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda p: None)

    res = nm3u8dl._remux_fix(str(chemin))

    assert res == str(chemin)
    assert the_proc.killed is True
    assert chemin.read_bytes() == b"ORIGINAL"
