import types
from types import SimpleNamespace

import pytest

import engine.download._engine_utils as engine_utils
import engine.download.methods._proc_registry as pr


@pytest.fixture(autouse=True)
def _isoler_etat_global():
    actifs_snap = set(pr._actifs)
    cancel_snap = pr._cancel_en_cours
    psutil_snap = pr._psutil
    pr._actifs.clear()
    pr._cancel_en_cours = False
    try:
        yield
    finally:
        pr._actifs.clear()
        pr._actifs.update(actifs_snap)
        pr._cancel_en_cours = cancel_snap
        pr._psutil = psutil_snap


class _FakeProc:
    def __init__(self, pid=1, code=None):
        self.pid = pid
        self._code = code

    def poll(self):
        return self._code


def _fake_proc(pid=1, code=None):
    return _FakeProc(pid=pid, code=code)


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, proc):
        self.calls.append(proc)


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(engine_utils, "terminate_tree", rec)
    return rec


def test_register_proc_none_noop(recorder):
    pr.register_proc(None)
    assert pr._actifs == set()
    assert recorder.calls == []


def test_register_proc_adds_to_actifs(recorder):
    p = _fake_proc(pid=10)
    pr.register_proc(p)
    assert p in pr._actifs
    assert recorder.calls == []


def test_register_during_cancel_not_added_and_terminated(recorder):
    pr._cancel_en_cours = True
    p = _fake_proc(pid=11)
    pr.register_proc(p)
    assert p not in pr._actifs
    assert recorder.calls == [p]


def test_unregister_proc_removes(recorder):
    p = _fake_proc(pid=12)
    pr.register_proc(p)
    assert p in pr._actifs
    pr.unregister_proc(p)
    assert p not in pr._actifs


def test_unregister_proc_none_noop(recorder):
    p = _fake_proc(pid=13)
    pr.register_proc(p)
    before = set(pr._actifs)
    pr.unregister_proc(None)
    assert pr._actifs == before
    assert p in pr._actifs


def test_register_purges_finished(recorder):
    vivant = _fake_proc(pid=1, code=None)
    fini = _fake_proc(pid=2, code=0)
    pr._actifs.add(vivant)
    pr._actifs.add(fini)
    pr.register_proc(_fake_proc(pid=3, code=None))
    assert fini not in pr._actifs
    assert vivant in pr._actifs


def test_purger_drops_finished():
    vivant = _fake_proc(pid=1, code=None)
    fini = _fake_proc(pid=2, code=7)
    pr._actifs.add(vivant)
    pr._actifs.add(fini)
    pr._purger_process_termines_verrou_tenu()
    assert pr._actifs == {vivant}


def test_est_fini_true_for_finished_and_bad_handle():
    assert pr._est_fini(_fake_proc(code=0)) is True
    assert pr._est_fini(_fake_proc(code=None)) is False

    def _boom():
        raise OSError("handle invalide")

    assert pr._est_fini(SimpleNamespace(pid=9, poll=_boom)) is True


def test_kill_all_processes_terminates_live_skips_finished(recorder):
    vivant_a = _fake_proc(pid=21, code=None)
    vivant_b = _fake_proc(pid=22, code=None)
    fini = _fake_proc(pid=23, code=0)
    pr._actifs.update({vivant_a, vivant_b, fini})

    tues = pr.kill_all_processes()

    assert tues == 2
    assert pr._actifs == set()
    assert pr._cancel_en_cours is False
    assert set(recorder.calls) == {vivant_a, vivant_b}
    assert fini not in recorder.calls


def test_kill_all_processes_empty_returns_zero(recorder):
    assert pr.kill_all_processes() == 0
    assert recorder.calls == []
    assert pr._cancel_en_cours is False


def test_kill_all_processes_swallows_exceptions(recorder, monkeypatch):
    def _boom(proc):
        raise RuntimeError("terminate cassé")

    monkeypatch.setattr(engine_utils, "terminate_tree", _boom)
    vivant = _fake_proc(pid=31, code=None)
    pr._actifs.add(vivant)

    tues = pr.kill_all_processes()

    assert tues == 0
    assert pr._actifs == set()
    assert pr._cancel_en_cours is False


class _FakePsutilProc:
    def __init__(self, pid, children=None, status_value="running"):
        self.pid = pid
        self._children = children or []
        self._status = status_value
        self.suspended = 0
        self.resumed = 0

    def children(self, recursive=True):
        return list(self._children)

    def suspend(self):
        self.suspended += 1

    def resume(self):
        self.resumed += 1

    def status(self):
        return self._status


def _fake_psutil_module(registry, status_value="running"):
    mod = types.ModuleType("fake_psutil")
    mod.STATUS_STOPPED = "stopped"

    def _Process(pid):
        if pid in registry:
            return registry[pid]
        return _FakePsutilProc(pid, status_value=status_value)

    mod.Process = _Process
    return mod


def test_psutil_tree_none_returns_empty(monkeypatch):
    monkeypatch.setattr(pr, "_psutil", None)
    assert pr._psutil_tree(_fake_proc(pid=5)) == []


def test_psutil_tree_returns_proc_and_children(monkeypatch):
    child = _FakePsutilProc(pid=99)
    parent = _FakePsutilProc(pid=40, children=[child])
    mod = _fake_psutil_module({40: parent})
    monkeypatch.setattr(pr, "_psutil", mod)

    tree = pr._psutil_tree(_fake_proc(pid=40))

    assert tree == [parent, child]


def test_psutil_tree_swallows_process_error(monkeypatch):
    mod = types.ModuleType("fake_psutil")

    def _Process(pid):
        raise RuntimeError("no such process")

    mod.Process = _Process
    monkeypatch.setattr(pr, "_psutil", mod)

    assert pr._psutil_tree(_fake_proc(pid=41)) == []


def test_suspend_all_applies_across_tree(monkeypatch):
    child = _FakePsutilProc(pid=51)
    parent = _FakePsutilProc(pid=50, children=[child])
    mod = _fake_psutil_module({50: parent})
    monkeypatch.setattr(pr, "_psutil", mod)

    live = _fake_proc(pid=50, code=None)
    pr._actifs.add(live)

    n = pr.suspend_all()

    assert n == 2
    assert parent.suspended == 1
    assert child.suspended == 1


def test_resume_all_applies_across_tree(monkeypatch):
    child = _FakePsutilProc(pid=61)
    parent = _FakePsutilProc(pid=60, children=[child])
    mod = _fake_psutil_module({60: parent})
    monkeypatch.setattr(pr, "_psutil", mod)

    live = _fake_proc(pid=60, code=None)
    pr._actifs.add(live)

    n = pr.resume_all()

    assert n == 2
    assert parent.resumed == 1
    assert child.resumed == 1


def test_apply_tree_skips_finished_proc(monkeypatch):
    parent = _FakePsutilProc(pid=70)
    mod = _fake_psutil_module({70: parent})
    monkeypatch.setattr(pr, "_psutil", mod)

    pr._actifs.add(_fake_proc(pid=70, code=0))

    assert pr.suspend_all() == 0
    assert parent.suspended == 0


def test_apply_tree_skips_proc_with_bad_poll(monkeypatch):
    parent = _FakePsutilProc(pid=71)
    mod = _fake_psutil_module({71: parent})
    monkeypatch.setattr(pr, "_psutil", mod)

    class _BadPoll:
        pid = 71

        def poll(self):
            raise OSError("handle")

    pr._actifs.add(_BadPoll())

    assert pr.suspend_all() == 0
    assert parent.suspended == 0


def test_apply_tree_counts_only_successful_actions(monkeypatch):
    class _PartialProc(_FakePsutilProc):
        def suspend(self):
            raise RuntimeError("permission refusée")

    child = _FakePsutilProc(pid=81)
    parent = _PartialProc(pid=80, children=[child])
    mod = _fake_psutil_module({80: parent})
    monkeypatch.setattr(pr, "_psutil", mod)

    pr._actifs.add(_fake_proc(pid=80, code=None))

    n = pr.suspend_all()

    assert n == 1
    assert child.suspended == 1


def test_suspend_all_psutil_none_returns_zero(monkeypatch):
    monkeypatch.setattr(pr, "_psutil", None)
    pr._actifs.add(_fake_proc(pid=90, code=None))
    assert pr.suspend_all() == 0


def test_resume_all_psutil_none_returns_zero(monkeypatch):
    monkeypatch.setattr(pr, "_psutil", None)
    pr._actifs.add(_fake_proc(pid=91, code=None))
    assert pr.resume_all() == 0


def test_is_suspended_true_when_status_stopped(monkeypatch):
    parent = _FakePsutilProc(pid=100, status_value="stopped")
    mod = _fake_psutil_module({100: parent})
    monkeypatch.setattr(pr, "_psutil", mod)
    assert pr.is_suspended(_fake_proc(pid=100)) is True


def test_is_suspended_false_when_status_running(monkeypatch):
    parent = _FakePsutilProc(pid=101, status_value="running")
    mod = _fake_psutil_module({101: parent})
    monkeypatch.setattr(pr, "_psutil", mod)
    assert pr.is_suspended(_fake_proc(pid=101)) is False


def test_is_suspended_false_when_psutil_none(monkeypatch):
    monkeypatch.setattr(pr, "_psutil", None)
    assert pr.is_suspended(_fake_proc(pid=102)) is False


def test_is_suspended_false_when_proc_none(monkeypatch):
    mod = _fake_psutil_module({})
    monkeypatch.setattr(pr, "_psutil", mod)
    assert pr.is_suspended(None) is False


def test_is_suspended_false_on_process_error(monkeypatch):
    mod = types.ModuleType("fake_psutil")
    mod.STATUS_STOPPED = "stopped"

    def _Process(pid):
        raise RuntimeError("no such process")

    mod.Process = _Process
    monkeypatch.setattr(pr, "_psutil", mod)
    assert pr.is_suspended(_fake_proc(pid=103)) is False
