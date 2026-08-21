import json
import os

import pytest

import engine.cache.cover_images as ci
import engine.cache.covers as cov
import engine.config.settings as settings
from engine.download import _engine_utils as u


@pytest.fixture(autouse=True)
def _reset_inflight():
    snap = set(ci._inflight)
    ci._inflight.clear()
    yield
    ci._inflight.clear()
    ci._inflight.update(snap)


@pytest.fixture(autouse=True)
def _reset_covers_cache():
    snap = dict(cov._covers_cache)
    yield
    cov._covers_cache.clear()
    cov._covers_cache.update(snap)


def test_fmt_speed_thresholds_extra():
    assert u.fmt_speed(1_000_000) == "1.0 MB/s"
    assert u.fmt_speed(999_999) == "1000 KB/s"
    assert u.fmt_speed(1_000) == "1 KB/s"
    assert u.fmt_speed(999) == "999 B/s"
    assert u.fmt_speed(1) == "1 B/s"


def test_fmt_eta_hours_and_zero_floor():
    assert u.fmt_eta(-10) == ""
    assert u.fmt_eta(60) == "1m00s"
    assert u.fmt_eta(3600) == "1h00m"
    assert u.fmt_eta(7325) == "2h02m"


def test_supprimer_silencieux_handles_oserror(monkeypatch, tmp_path):
    f = tmp_path / "locked.txt"
    f.write_text("x", encoding="utf-8")

    def _boom(_path):
        raise OSError("busy")

    monkeypatch.setattr(u.os, "remove", _boom)
    u.supprimer_silencieux(str(f))
    assert f.exists()


def test_clean_subprocess_env_without_meipass(monkeypatch):
    monkeypatch.delattr(u.sys, "_MEIPASS", raising=False)
    fake_env = {"PATH": "/a:/b", "_PYI_X": "1", "FOO": "bar"}
    monkeypatch.setattr(u.os, "environ", fake_env)
    out = u.clean_subprocess_env()
    assert out == fake_env
    assert out is not fake_env
    assert out["_PYI_X"] == "1"


def test_clean_subprocess_env_with_meipass_strips_path_and_pyi(monkeypatch):
    meipass = os.path.normpath("/bundle/dir")
    monkeypatch.setattr(u.sys, "_MEIPASS", meipass, raising=False)
    sep = os.pathsep
    fake_env = {
        "PATH": sep.join([meipass, "/usr/bin", "/bundle/dir", "/opt"]),
        "LD_LIBRARY_PATH": sep.join([meipass, "/lib"]),
        "_PYI_SPLASH": "x",
        "_PYI_OTHER": "y",
        "KEEP": "1",
    }
    monkeypatch.setattr(u.os, "environ", fake_env)
    out = u.clean_subprocess_env()
    norm = os.path.normcase(os.path.normpath(meipass))
    remaining = [
        os.path.normcase(os.path.normpath(p))
        for p in out["PATH"].split(sep)
        if p
    ]
    assert norm not in remaining
    assert os.path.normcase(os.path.normpath("/usr/bin")) in remaining
    assert os.path.normcase(os.path.normpath("/opt")) in remaining
    assert out["LD_LIBRARY_PATH"] == "/lib"
    assert "_PYI_SPLASH" not in out
    assert "_PYI_OTHER" not in out
    assert out["KEEP"] == "1"


def test_clean_subprocess_env_meipass_empty_var_skipped(monkeypatch):
    meipass = os.path.normpath("/bundle/dir")
    monkeypatch.setattr(u.sys, "_MEIPASS", meipass, raising=False)
    fake_env = {"PATH": "", "_PYI_Z": "z"}
    monkeypatch.setattr(u.os, "environ", fake_env)
    out = u.clean_subprocess_env()
    assert out["PATH"] == ""
    assert "_PYI_Z" not in out


class _FakeProc:
    def __init__(self, poll_value=None, pid=4321, poll_raises=False):
        self._poll_value = poll_value
        self._poll_raises = poll_raises
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.waited = []

    def poll(self):
        if self._poll_raises:
            raise RuntimeError("boom")
        return self._poll_value

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited.append(timeout)


def test_terminate_tree_none_is_noop():
    u.terminate_tree(None)


def test_terminate_tree_already_exited_returns(monkeypatch):
    calls = []
    monkeypatch.setattr(u.subprocess, "run", lambda *a, **k: calls.append(a))
    proc = _FakeProc(poll_value=0)
    u.terminate_tree(proc)
    assert calls == []
    assert proc.terminated is False


def test_terminate_tree_poll_raises_returns(monkeypatch):
    calls = []
    monkeypatch.setattr(u.subprocess, "run", lambda *a, **k: calls.append(a))
    proc = _FakeProc(poll_raises=True)
    u.terminate_tree(proc)
    assert calls == []
    assert proc.terminated is False


def test_terminate_tree_nt_uses_taskkill(monkeypatch):
    recorded = {}

    def _run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["kwargs"] = kwargs

    monkeypatch.setattr(u.os, "name", "nt")
    monkeypatch.setattr(u.subprocess, "run", _run)
    proc = _FakeProc(poll_value=None, pid=9999)
    u.terminate_tree(proc)
    assert recorded["cmd"] == ["taskkill", "/F", "/T", "/PID", "9999"]
    assert recorded["kwargs"]["timeout"] == 10
    assert proc.terminated is False


def test_terminate_tree_nt_taskkill_fails_falls_back(monkeypatch):
    def _run(*a, **k):
        raise OSError("no taskkill")

    monkeypatch.setattr(u.os, "name", "nt")
    monkeypatch.setattr(u.subprocess, "run", _run)
    proc = _FakeProc(poll_value=None)
    u.terminate_tree(proc)
    assert proc.terminated is True
    assert proc.waited == [3]


def test_terminate_tree_posix_terminates(monkeypatch):
    def _run(*a, **k):
        raise AssertionError("subprocess.run must not run on posix branch")

    monkeypatch.setattr(u.os, "name", "posix")
    monkeypatch.setattr(u.subprocess, "run", _run)
    proc = _FakeProc(poll_value=None)
    u.terminate_tree(proc)
    assert proc.terminated is True
    assert proc.waited == [3]
    assert proc.killed is False


def test_terminate_tree_posix_terminate_fails_kills(monkeypatch):
    monkeypatch.setattr(u.os, "name", "posix")

    class _BadProc(_FakeProc):
        def terminate(self):
            raise RuntimeError("cannot terminate")

    proc = _BadProc(poll_value=None)
    u.terminate_tree(proc)
    assert proc.killed is True


def test_cached_file_returns_existing_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    url = "https://cdn.example.com/poster.png"
    target = (tmp_path / ci._key(url)).with_suffix(".png")
    target.write_bytes(b"PNGDATA")
    found = ci.cached_file(url)
    assert found == target
    assert found.exists()


def test_cached_file_prefers_jpg_over_png(monkeypatch, tmp_path):
    """When several encodings exist for the same key, the .jpg-first precedence wins."""
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    url = "https://cdn.example.com/poster2"
    base = tmp_path / ci._key(url)
    base.with_suffix(".png").write_bytes(b"PNG")
    base.with_suffix(".jpg").write_bytes(b"JPG")
    found = ci.cached_file(url)
    assert found.suffix == ".jpg"
    assert found.read_bytes() == b"JPG"


def test_warm_schedules_when_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    submitted = []

    def _fake_submit(fn):
        submitted.append(fn)

        class _F:
            pass

        return _F()

    monkeypatch.setattr(ci._executor, "submit", _fake_submit)
    url = "https://cdn.example.com/new.jpg"
    ci.warm(url)
    assert len(submitted) == 1
    assert url in ci._inflight


def test_warm_skips_when_already_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    url = "https://cdn.example.com/exists.png"
    (tmp_path / ci._key(url)).with_suffix(".png").write_bytes(b"x")

    def _fake_submit(_fn):
        raise AssertionError("must not schedule a cached url")

    monkeypatch.setattr(ci._executor, "submit", _fake_submit)
    ci.warm(url)
    assert url not in ci._inflight


def test_warm_dedups_inflight(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    submitted = []
    monkeypatch.setattr(ci._executor, "submit", lambda fn: submitted.append(fn))
    url = "https://cdn.example.com/dup.gif"
    ci._inflight.add(url)
    ci.warm(url)
    assert submitted == []


def test_warm_runner_calls_fetch_and_clears_inflight(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    fetched = []
    monkeypatch.setattr(ci, "fetch_and_store", lambda u_: fetched.append(u_))
    captured = {}
    monkeypatch.setattr(ci._executor, "submit", lambda fn: captured.setdefault("fn", fn))
    url = "https://cdn.example.com/run.webp"
    ci.warm(url)
    assert url in ci._inflight
    captured["fn"]()
    assert fetched == [url]
    assert url not in ci._inflight


def test_warm_runtime_error_discards_inflight(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)

    def _boom(_fn):
        raise RuntimeError("executor shut down")

    monkeypatch.setattr(ci._executor, "submit", _boom)
    url = "https://cdn.example.com/late.jpg"
    ci.warm(url)
    assert url not in ci._inflight


def test_shutdown_covers_delegates_to_executor(monkeypatch):
    recorded = {}

    class _FakeExec:
        def shutdown(self, **kwargs):
            recorded["kwargs"] = kwargs

    monkeypatch.setattr(ci, "_executor", _FakeExec())
    ci.shutdown_covers()
    assert recorded["kwargs"]["wait"] is False
    assert recorded["kwargs"]["cancel_futures"] is True


def test_evict_old_files_removes_oldest(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "MAX_FILES", 2)
    for i in range(5):
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    ci._evict_old_files()
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == ["f3.jpg", "f4.jpg"]


def test_evict_old_files_noop_under_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ci, "MAX_FILES", 10)
    (tmp_path / "only.jpg").write_bytes(b"x")
    ci._evict_old_files()
    assert (tmp_path / "only.jpg").exists()


def test_covers_file_uses_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    assert cov._covers_file() == tmp_path / "covers.json"


def test_save_and_load_covers_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    payload = {"a": "url-a", "b": "url-b"}
    assert cov._save_covers(payload) is True
    assert (tmp_path / "covers.json").exists()
    assert cov._load_covers() == payload


def test_load_covers_missing_file_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    assert cov._load_covers() == {}


def test_load_covers_corrupt_not_dict_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    (tmp_path / "covers.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert cov._load_covers() == {}


def test_load_covers_invalid_json_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    (tmp_path / "covers.json").write_text("{not json", encoding="utf-8")
    assert cov._load_covers() == {}


def test_load_covers_truncates_to_max_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cov, "COVERS_MAX_ENTRIES", 3)
    big = {f"k{i}": f"v{i}" for i in range(6)}
    (tmp_path / "covers.json").write_text(json.dumps(big), encoding="utf-8")
    out = cov._load_covers()
    assert len(out) == 3
    assert list(out.keys()) == ["k3", "k4", "k5"]


def test_load_covers_keeps_when_at_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cov, "COVERS_MAX_ENTRIES", 3)
    data = {"k0": "v0", "k1": "v1", "k2": "v2"}
    (tmp_path / "covers.json").write_text(json.dumps(data), encoding="utf-8")
    out = cov._load_covers()
    assert out == data


def test_save_covers_failure_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(cov.os, "replace", _boom)
    assert cov._save_covers({"a": "b"}) is False
