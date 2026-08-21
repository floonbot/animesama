from engine.download.queue import DownloadQueue


def _q_with(items):
    q = DownloadQueue()
    for it in items:
        q._queue.append(it)
    return q

def test_deplacer_reorders():
    q = _q_with([{"i": 0}, {"i": 1}, {"i": 2}])
    assert q.deplacer(0, 2) is True
    assert [x["i"] for x in q._queue] == [1, 2, 0]

def test_deplacer_same_index_is_noop_true():
    q = _q_with([{"i": 0}, {"i": 1}])
    assert q.deplacer(1, 1) is True
    assert [x["i"] for x in q._queue] == [0, 1]

def test_deplacer_out_of_range_false():
    q = _q_with([{"i": 0}])
    assert q.deplacer(0, 5) is False
    assert q.deplacer(3, 0) is False

def test_deplacer_bad_type_false():
    q = _q_with([{"i": 0}, {"i": 1}])
    assert q.deplacer("x", 0) is False

def test_retirer_removes():
    q = _q_with([{"i": 0}, {"i": 1}, {"i": 2}])
    assert q.retirer(1) is True
    assert [x["i"] for x in q._queue] == [0, 2]

def test_retirer_out_of_range_false():
    q = _q_with([{"i": 0}])
    assert q.retirer(5) is False

def test_retirer_bad_type_false():
    q = _q_with([{"i": 0}])
    assert q.retirer(None) is False

def test_pause_requires_current():
    q = DownloadQueue()
    assert q.pause() is False
    q._current = {"titre": "X"}
    assert q.pause() is True
    assert q.statut()["en_pause"] is True

def test_reprendre_clears_pause():
    q = DownloadQueue()
    q._current = {"t": 1}
    q.pause()
    assert q.reprendre() is True
    assert q.statut()["en_pause"] is False

def test_annuler_requires_current_then_keeps_queue():
    q = _q_with([{"i": 0}, {"i": 1}])
    assert q.annuler() is False
    q._current = {"t": 1}
    assert q.annuler() is True
    assert [x["i"] for x in q._queue] == [0, 1]
    assert q._cancelled.is_cancelled() is True

def test_ajouter_updates_queue_depth_max_gauge(monkeypatch):
    import asyncio

    from engine.observability.metrics import metrics

    metrics.reset()
    q = DownloadQueue()
    monkeypatch.setattr(q, "_start_worker", lambda: None)

    async def go():
        await q.ajouter({"a": 1})
        await q.ajouter({"a": 2})
        await q.ajouter({"a": 3})

    asyncio.run(go())
    assert metrics.gauges().get("queue_depth_max") == 3
    metrics.reset()

def test_queue_records_duration_metric(monkeypatch):
    import asyncio

    import engine.download.worker as w
    from engine.observability.metrics import metrics

    async def fake_traiter(item, q):
        await asyncio.sleep(0.01)

    monkeypatch.setattr(w, "traiter_item", fake_traiter)
    metrics.reset()
    q = DownloadQueue()
    q._queue.append({"x": 1})
    asyncio.run(q._run())
    snap = metrics.snapshot()
    assert snap.get("items_termines") == 1
    assert snap.get("temps_total_ms", 0) >= 0
    metrics.reset()
