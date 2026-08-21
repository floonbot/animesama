from engine.download.queue import DownloadQueue
from engine.download.store import DownloadStore


class _Recorder:
    def __init__(self) -> None:
        self.ops: list[tuple] = []

    def save_current_sync(self, item: dict) -> None:
        self.ops.append(("save", dict(item)))

    def clear_current_sync(self) -> None:
        self.ops.append(("clear_sync",))

    def clear_current(self) -> None:
        self.ops.append(("clear_async",))

    def save_queue(self, items: list) -> None:
        pass


def test_clear_current_uses_synchronous_store_path():
    q = DownloadQueue()
    q._store = _Recorder()

    q._save_current({"nom": "A"})
    q._clear_current()
    q._save_current({"nom": "B"})

    assert q._store.ops == [
        ("save", {"nom": "A"}),
        ("clear_sync",),
        ("save", {"nom": "B"}),
    ]
    assert not any(op[0] == "clear_async" for op in q._store.ops)


def test_clear_current_sync_is_immediately_durable_for_external_reader(tmp_path):
    a = DownloadStore(tmp_path / "d.db")
    try:
        a.save_current_sync({"nom": "A"})
        a.clear_current_sync()
        a.save_current_sync({"nom": "B"})
        b = DownloadStore(tmp_path / "d.db")
        try:
            assert b.load_current() == {"nom": "B"}
        finally:
            b.close()
    finally:
        a.close()


def test_clear_current_sync_removes_inflight_item(tmp_path):
    a = DownloadStore(tmp_path / "d.db")
    try:
        a.save_current_sync({"nom": "A"})
        a.clear_current_sync()
        assert a.load_current() is None
    finally:
        a.close()
