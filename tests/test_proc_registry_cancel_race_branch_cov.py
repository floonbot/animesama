import pytest

import engine.download._engine_utils as engine_utils
import engine.download.methods._proc_registry as pr


@pytest.fixture(autouse=True)
def _isoler_etat_global():
    actifs_snap = set(pr._actifs)
    cancel_snap = pr._cancel_en_cours
    pr._actifs.clear()
    pr._cancel_en_cours = False
    try:
        yield
    finally:
        pr._actifs.clear()
        pr._actifs.update(actifs_snap)
        pr._cancel_en_cours = cancel_snap


class _FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


def test_proc_registered_during_kill_window_is_not_left_orphan(monkeypatch):
    p1 = _FakeProc(pid=1)
    p2 = _FakeProc(pid=2)
    pr._actifs.add(p1)

    killed = []
    state = {"injected": False}

    def fake_terminate(proc):
        killed.append(proc)
        if not state["injected"]:
            state["injected"] = True
            pr.register_proc(p2)

    monkeypatch.setattr(engine_utils, "terminate_tree", fake_terminate)

    pr.kill_all_processes()

    assert p2 in killed or p2 not in pr._actifs, (
        f"p2 left orphan: killed={[p.pid for p in killed]}, actifs={[p.pid for p in pr._actifs]}"
    )
