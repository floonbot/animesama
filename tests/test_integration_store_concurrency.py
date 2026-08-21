"""Gated real-IO integration test for SQLite store concurrency.

Marked ``integration`` so the default fast/deterministic suite skips it
(``addopts = -m 'not integration'``). Run explicitly with::

    pytest -m integration

It drives the real :class:`engine.download.store.DownloadStore` (real sqlite3
connection, real WAL journal on a real on-disk file, real single-writer
``ThreadPoolExecutor`` and real ``threading.Lock``) from many concurrent OS
threads. The default deterministic suite injects faults on a single thread and
never exercises true thread contention; this test asserts that hammering
``save_queue``/``append_history``/``save_current``/``clear_current`` and the
matching loaders from real threads produces no corruption, no
``database is locked`` / ``OperationalError``, and a consistent final state.
No network, no external binary, no real time/sleep dependence.
"""

import sqlite3
import threading

import pytest

from engine.download.store import DownloadStore

pytestmark = pytest.mark.integration


def test_store_concurrent_writes_no_corruption(tmp_path):
    db = tmp_path / "concurrency.db"
    store = DownloadStore(db)

    writers = 8
    rounds = 60
    barrier = threading.Barrier(writers)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def record(exc: BaseException) -> None:
        with errors_lock:
            errors.append(exc)

    def queue_writer(worker: int) -> None:
        try:
            barrier.wait()
            for r in range(rounds):
                items = [{"worker": worker, "round": r, "i": i} for i in range(5)]
                store.save_queue(items)
                store.load_queue()
        except BaseException as exc:  # noqa: BLE001
            record(exc)

    def history_writer(worker: int) -> None:
        try:
            barrier.wait()
            for r in range(rounds):
                store.append_history({"worker": worker, "round": r}, cap=50)
                store.load_history(cap=50)
        except BaseException as exc:  # noqa: BLE001
            record(exc)

    def current_writer(worker: int) -> None:
        try:
            barrier.wait()
            for r in range(rounds):
                store.save_current({"worker": worker, "round": r})
                store.load_current()
                if r % 7 == 0:
                    store.clear_current()
        except BaseException as exc:  # noqa: BLE001
            record(exc)

    funcs = [queue_writer, history_writer, current_writer]
    threads = [
        threading.Thread(target=funcs[i % len(funcs)], args=(i,), name=f"w{i}")
        for i in range(writers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not any(t.is_alive() for t in threads), "a writer thread deadlocked"
    assert errors == [], f"concurrent store access raised: {errors!r}"

    store._flush()

    final_queue = store.load_queue()
    assert len(final_queue) == 5
    only_worker = {it["worker"] for it in final_queue}
    only_round = {it["round"] for it in final_queue}
    assert len(only_worker) == 1, f"queue interleaved across workers: {final_queue!r}"
    assert len(only_round) == 1, f"queue interleaved across rounds: {final_queue!r}"
    assert [it["i"] for it in final_queue] == [0, 1, 2, 3, 4]

    history = store.load_history(cap=50)
    assert 0 < len(history) <= 50, f"history cap violated: {len(history)}"

    final_current = store.load_current()
    assert final_current is None or set(final_current) == {"worker", "round"}

    store.close()

    probe = sqlite3.connect(str(db))
    try:
        assert probe.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert probe.execute("SELECT COUNT(*) FROM queue").fetchone()[0] == 5
        assert probe.execute("SELECT COUNT(*) FROM history").fetchone()[0] <= 50
        assert probe.execute("SELECT COUNT(*) FROM current").fetchone()[0] <= 1
    finally:
        probe.close()
