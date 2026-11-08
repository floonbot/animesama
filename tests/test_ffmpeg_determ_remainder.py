import logging
import subprocess
import threading

import pytest

from engine.download.methods import ffmpeg_engine


@pytest.fixture(autouse=True)
def _ecriture_directe(monkeypatch):
    # Ces tests visent l'analyse de la sortie de ffmpeg : ecriture directe.
    # Le passage par un dossier local : test_ecriture_locale_puis_livraison.py.
    def _sans_dossier_de_travail():
        raise OSError("ecriture directe")

    monkeypatch.setattr(ffmpeg_engine, "creer_dossier_de_travail", _sans_dossier_de_travail)


class _ListPipe:
    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)


class _FakeProc:
    def __init__(
        self,
        stdout_lines=None,
        stderr_lines=None,
        returncode=0,
        poll_value=None,
        wait_raises=False,
    ):
        self.returncode = returncode
        self.pid = 4321
        self._poll_value = poll_value
        self._wait_raises = wait_raises
        self.wait_calls = []
        self.killed = False
        self.terminated = False
        self.stdout = None if stdout_lines is None else _ListPipe(stdout_lines)
        self.stderr = None if stderr_lines is None else _ListPipe(stderr_lines)

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self._wait_raises:
            self._wait_raises = False
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout)
        return self.returncode

    def poll(self):
        return self._poll_value

    def kill(self):
        self.killed = True

    def terminate(self):
        self.terminated = True


class _FakePopenFactory:
    def __init__(self, proc=None, raises=None):
        self.proc = proc
        self.raises = raises
        self.cmd = None
        self.kwargs = None

    def __call__(self, cmd, *args, **kwargs):
        self.cmd = list(cmd)
        self.kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return self.proc


class _FixedClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture(autouse=True)
def _snapshot_ffmpeg_globals(monkeypatch):
    saved_path = ffmpeg_engine._FFMPEG_PATH
    saved_taille = ffmpeg_engine.TAILLE_MIN_FICHIER
    terminate_calls = []
    monkeypatch.setattr(ffmpeg_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(ffmpeg_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "_terminate_tree", lambda p: terminate_calls.append(p))
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a: 0.0)
    monkeypatch.setattr(ffmpeg_engine.time, "time", _FixedClock())
    yield terminate_calls
    ffmpeg_engine._FFMPEG_PATH = saved_path
    ffmpeg_engine.TAILLE_MIN_FICHIER = saved_taille


def test_ffmpeg_no_exe_returns_none_and_warns_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: None)

    def _no_popen(*a, **k):
        raise AssertionError("Popen must not be reached without an exe")

    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", _no_popen)

    calls = []
    res = ffmpeg_engine.ffmpeg_download(
        "http://host/x.m3u8", str(tmp_path), "ep",
        callback=lambda p, t: calls.append((p, t)),
    )

    assert res is None
    assert len(calls) == 1
    assert calls[0][0] == 0.0
    assert "introuvable" in calls[0][1]


def test_ffmpeg_invalid_url_returns_none_without_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")

    def _no_popen(*a, **k):
        raise AssertionError("Popen must not run on an invalid url")

    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", _no_popen)

    def _no_makedirs(*a, **k):
        raise AssertionError("makedirs must not run on an invalid url")

    monkeypatch.setattr(ffmpeg_engine.os, "makedirs", _no_makedirs)

    res = ffmpeg_engine.ffmpeg_download("ftp://host/x", str(tmp_path), "ep")

    assert res is None


def test_ffmpeg_stderr_error_keyword_is_logged(tmp_path, monkeypatch, caplog):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    factory = _FakePopenFactory(_FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1", "Invalid data found when processing input"],
        returncode=0,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)

    with caplog.at_level(logging.WARNING, logger="engine.download.methods.ffmpeg_engine"):
        res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(sortie)
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Invalid data found when processing input" in m for m in warnings)
    assert "ffmpeg" in factory.cmd
    assert "http://host/x.m3u8" in factory.cmd


def test_ffmpeg_stderr_benign_line_not_logged_as_warning(tmp_path, monkeypatch, caplog):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    factory = _FakePopenFactory(_FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1 progressing nicely"],
        returncode=0,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)

    with caplog.at_level(logging.WARNING, logger="engine.download.methods.ffmpeg_engine"):
        res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(sortie)
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("frame=1 fps=1 progressing nicely" in m for m in warnings)


def test_ffmpeg_wait_timeout_terminates_tree_after_eof(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    proc = _FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1"],
        returncode=0,
        poll_value=0,
        wait_raises=True,
    )
    factory = _FakePopenFactory(proc)
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)

    terminate_calls = []
    monkeypatch.setattr(ffmpeg_engine, "_terminate_tree", lambda p: terminate_calls.append(p))

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(sortie)
    assert proc.wait_calls[0] == 30
    assert terminate_calls == [proc]


def test_ffmpeg_finally_removes_undersized_file_on_failure(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 64)

    factory = _FakePopenFactory(_FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1"],
        returncode=1,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1024)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert not sortie.exists()


def test_ffmpeg_finally_keeps_large_file_on_failure(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"y" * 2048)

    factory = _FakePopenFactory(_FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1"],
        returncode=1,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1024)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert sortie.exists()
    assert sortie.stat().st_size == 2048


def test_ffmpeg_filenotfound_on_popen_returns_none(tmp_path, monkeypatch):
    factory = _FakePopenFactory(raises=FileNotFoundError("ffmpeg vanished"))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert factory.cmd[0] == "ffmpeg"


def test_ffmpeg_generic_exception_on_popen_returns_none(tmp_path, monkeypatch):
    factory = _FakePopenFactory(raises=ValueError("kaboom"))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None


def test_ffmpeg_zero_returncode_no_output_file_returns_none(tmp_path, monkeypatch):
    factory = _FakePopenFactory(_FakeProc(
        stdout_lines=[],
        stderr_lines=["frame=1 fps=1"],
        returncode=0,
    ))
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1)

    res = ffmpeg_engine.ffmpeg_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res is None
    assert not (tmp_path / "ep.mp4").exists()
