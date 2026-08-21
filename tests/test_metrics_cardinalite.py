import logging

import pytest

from engine.observability.metrics import COUNTERS_MAX, Metrics


@pytest.fixture
def m():
    return Metrics()


def test_les_compteurs_sont_plafonnes(m):
    for i in range(COUNTERS_MAX + 500):
        m.incr(f"host_attempt_{i}")

    assert len(m._counters) <= COUNTERS_MAX


def test_une_cle_existante_continue_de_s_incrementer_au_dela_du_plafond(m):
    m.incr("host_attempt_connu", 1)
    for i in range(COUNTERS_MAX + 100):
        m.incr(f"host_attempt_{i}")

    m.incr("host_attempt_connu", 5)

    assert m._counters["host_attempt_connu"] == 6


def test_le_warning_n_est_logge_qu_une_fois(m, caplog):
    with caplog.at_level(logging.WARNING, logger="engine.observability.metrics"):
        for i in range(COUNTERS_MAX + 300):
            m.incr(f"host_attempt_{i}")

    avertissements = [r for r in caplog.records if "métrique" in r.message.lower()]
    assert len(avertissements) == 1


def test_incr_reste_infaillible(m):
    m.incr("ok", 1)
    m.incr("mauvais", "pas un entier")
    m.incr("zero", 0)
    m.incr(None)

    assert m._counters["ok"] == 1
    assert "mauvais" not in m._counters
    assert "zero" not in m._counters
