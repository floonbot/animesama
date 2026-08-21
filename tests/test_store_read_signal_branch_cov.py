import sqlite3

import pytest

from engine.download.store import DownloadStore


class _BoomConn:
    def execute(self, *a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    def close(self):
        return None


@pytest.fixture
def store(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    yield s
    s.close()


@pytest.mark.parametrize("method", ["load_queue", "load_history", "load_current"])
def test_read_error_is_observable_and_graceful(store, method):
    from engine.observability.metrics import metrics
    metrics.reset()

    # La vraie connexion doit etre fermee avant d'etre remplacee : sinon elle
    # n'est plus jointe par personne et fuit jusqu'au ramasse-miettes
    # (ResourceWarning « unclosed database »).
    store._conn.close()
    store._conn = _BoomConn()
    result = getattr(store, method)()

    assert result in ([], None)
    snap = metrics.snapshot()
    metrics.reset()
    assert snap.get("store_read_error", 0) >= 1
