import engine.observability.metrics as metrics_mod
from engine.download.queue import DownloadQueue


class _FakeMetrics:
    def __init__(self):
        self.gauges = {}

    def set_gauge(self, name, value):
        self.gauges[name] = value


class _FakeStore:
    def load_queue(self):
        return []

    def load_history(self):
        return []

    def load_current(self):
        return None


def test_health_queue_reports_persistence_flag(monkeypatch):
    from engine.download.queue import queue
    from web.api.routes import health

    monkeypatch.setattr(queue, "_store", object())
    assert health._health_queue()["persistence"] is True

    monkeypatch.setattr(queue, "_store", None)
    assert health._health_queue()["persistence"] is False


def test_enable_persistence_sets_gauge_one_on_success(monkeypatch):
    fm = _FakeMetrics()
    monkeypatch.setattr(metrics_mod, "metrics", fm)
    monkeypatch.setattr("engine.download.store.DownloadStore", lambda *a, **k: _FakeStore())

    q = DownloadQueue()
    q.enable_persistence()

    assert fm.gauges.get("persistence_enabled") == 1


def test_enable_persistence_sets_gauge_zero_on_failure(monkeypatch):
    fm = _FakeMetrics()
    monkeypatch.setattr(metrics_mod, "metrics", fm)

    def _boom(*a, **k):
        raise RuntimeError("db locked")

    monkeypatch.setattr("engine.download.store.DownloadStore", _boom)

    q = DownloadQueue()
    q.enable_persistence()

    assert fm.gauges.get("persistence_enabled") == 0
    assert q._store is None
