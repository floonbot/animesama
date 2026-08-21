import engine.download.worker as worker
from engine.download.worker import _est_annule, _historique_ajouter, _historique_append


class _FakeFlag:
    def __init__(self, v):
        self._v = v
    def is_cancelled(self):
        return self._v

class _FakeQueue:
    def __init__(self, cancelled=False):
        self._cancelled = _FakeFlag(cancelled)
        self._history = []

def test_est_annule_with_flag_object():
    assert _est_annule(_FakeQueue(cancelled=True)) is True
    assert _est_annule(_FakeQueue(cancelled=False)) is False

def test_est_annule_with_list_fallback():
    class Q:
        _cancelled = [True]
    assert _est_annule(Q()) is True

def test_est_annule_missing_attr_is_false():
    class Q:
        pass
    assert _est_annule(Q()) is False

def test_historique_append_and_cap():
    q = _FakeQueue()
    for i in range(worker.HISTORIQUE_MAX + 5):
        _historique_append(q, {"i": i})
    assert len(q._history) == worker.HISTORIQUE_MAX
    assert q._history[0]["i"] == 5
    assert q._history[-1]["i"] == worker.HISTORIQUE_MAX + 4

def test_historique_ajouter_builds_entry():
    q = _FakeQueue()
    _historique_ajouter(q, "Titre", "VOSTFR", succes=3, echoues=1, skipped=2)
    assert q._history[-1] == {
        "titre": "Titre", "langue": "VOSTFR",
        "succes": 3, "echoues": 1, "skipped": 2,
    }
