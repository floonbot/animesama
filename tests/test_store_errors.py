import sqlite3

import pytest

import engine.observability.metrics as metrics_mod
from engine.download.store import DownloadStore


class _FakeMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def incr(self, name: str, n: int = 1) -> None:
        self.calls.append((name, n))


class _ConnProxy:
    def __init__(self, real) -> None:
        self._real = real
        self.fail = False

    def execute(self, *args, **kwargs):
        if self.fail:
            raise sqlite3.OperationalError("boom")
        return self._real.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        if self.fail:
            raise sqlite3.OperationalError("boom")
        return self._real.executemany(*args, **kwargs)

    def commit(self):
        return self._real.commit()

    def close(self):
        return self._real.close()


@pytest.fixture
def fake_metrics(monkeypatch):
    fm = _FakeMetrics()
    monkeypatch.setattr(metrics_mod, "metrics", fm)
    return fm


@pytest.fixture
def store(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    s._conn = _ConnProxy(s._conn)
    yield s
    s.close()


def _break(store) -> None:
    store._conn.fail = True


def test_save_queue_sync_swallows_sqlite_error_and_counts(store, fake_metrics):
    _break(store)
    store._save_queue_sync([(0, "{}")])
    assert fake_metrics.calls == [("store_write_error", 1)]


def test_append_history_sync_swallows_sqlite_error_and_counts(store, fake_metrics):
    _break(store)
    store._append_history_sync("{}", 200)
    assert fake_metrics.calls == [("store_write_error", 1)]


def test_save_current_sync_swallows_sqlite_error_and_counts(store, fake_metrics):
    _break(store)
    store._save_current_sync("{}")
    assert fake_metrics.calls == [("store_write_error", 1)]


def test_clear_current_sync_swallows_sqlite_error_and_counts(store, fake_metrics):
    _break(store)
    store._clear_current_sync()
    assert fake_metrics.calls == [("store_write_error", 1)]


def test_public_save_queue_does_not_raise_when_execute_fails(store, fake_metrics):
    _break(store)
    store.save_queue([{"a": 1}])
    store._flush()
    assert ("store_write_error", 1) in fake_metrics.calls


def test_public_append_history_does_not_raise_when_execute_fails(store, fake_metrics):
    _break(store)
    store.append_history({"a": 1})
    store._flush()
    assert ("store_write_error", 1) in fake_metrics.calls


def test_public_save_current_does_not_raise_when_execute_fails(store, fake_metrics):
    _break(store)
    store.save_current({"a": 1})
    store._flush()
    assert ("store_write_error", 1) in fake_metrics.calls


def test_public_clear_current_does_not_raise_when_execute_fails(store, fake_metrics):
    _break(store)
    store.clear_current()
    store._flush()
    assert ("store_write_error", 1) in fake_metrics.calls


def test_load_queue_returns_empty_on_execute_error(store):
    _break(store)
    assert store.load_queue() == []


def test_load_history_returns_empty_on_execute_error(store):
    _break(store)
    assert store.load_history() == []


def test_load_current_returns_none_on_execute_error(store):
    _break(store)
    assert store.load_current() is None


def test_submit_when_closed_does_not_submit(store):
    store._closed = True
    seen = []
    store._submit(lambda *a: seen.append(a), 1, 2)
    store._closed = False
    store._flush()
    assert seen == []


def test_submit_swallows_runtime_error_from_executor(store, monkeypatch):
    def boom_submit(*_a, **_k):
        raise RuntimeError("shutdown")

    monkeypatch.setattr(store._writer, "submit", boom_submit)
    store._submit(lambda: None)


def test_log_writer_error_logs_and_counts_when_future_has_exception(store, fake_metrics):
    class _Fut:
        def exception(self):
            return ValueError("nope")

    store._log_writer_error(_Fut())
    assert fake_metrics.calls == [("store_write_error", 1)]


def test_log_writer_error_noop_when_future_has_no_exception(store, fake_metrics):
    class _Fut:
        def exception(self):
            return None

    store._log_writer_error(_Fut())
    assert fake_metrics.calls == []


def test_flush_swallows_exception_from_submit(store, monkeypatch):
    def boom_submit(*_a, **_k):
        raise RuntimeError("dead")

    monkeypatch.setattr(store._writer, "submit", boom_submit)
    store._flush()


def test_save_queue_sync_counts_once_per_failed_call(store, fake_metrics):
    _break(store)
    store._save_queue_sync([(0, "{}")])
    store._save_queue_sync([(0, "{}")])
    assert fake_metrics.calls == [("store_write_error", 1), ("store_write_error", 1)]


def test_metric_write_error_swallows_metrics_import_failure(store, monkeypatch):
    class _Broken:
        def incr(self, *_a, **_k):
            raise RuntimeError("metrics down")

    monkeypatch.setattr(metrics_mod, "metrics", _Broken())
    _break(store)
    store._clear_current_sync()


def test_load_current_returns_none_then_recovers_when_error_clears(store):
    store.save_current({"nom": "A"})
    assert store.load_current() == {"nom": "A"}
    _break(store)
    assert store.load_current() is None
    store._conn.fail = False
    assert store.load_current() == {"nom": "A"}
