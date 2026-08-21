import sqlite3

import pytest

from engine.download.store import DownloadStore


class _PartialFailConn:
    def __init__(self, real) -> None:
        self._real = real
        self.fail_executemany = False

    def execute(self, *args, **kwargs):
        return self._real.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        if self.fail_executemany:
            raise sqlite3.OperationalError("boom")
        return self._real.executemany(*args, **kwargs)

    def commit(self):
        return self._real.commit()

    def rollback(self):
        return self._real.rollback()

    def close(self):
        return self._real.close()


@pytest.fixture
def store(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    yield s
    s.close()


def test_write_rolls_back_partial_transaction_so_next_commit_keeps_queue(store):
    store.save_queue([{"nom": "A"}])
    store._flush()
    assert store.load_queue() == [{"nom": "A"}]

    proxy = _PartialFailConn(store._conn)
    store._conn = proxy

    proxy.fail_executemany = True
    store._save_queue_sync([(0, '{"nom": "B"}')])
    proxy.fail_executemany = False

    store._save_current_sync('{"nom": "cur"}')

    assert store.load_queue() == [{"nom": "A"}]
    assert store.load_current() == {"nom": "cur"}
