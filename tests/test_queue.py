from engine.download.queue import CancelToken, DownloadQueue


def test_cancel_token_states():
    t = CancelToken()
    assert t.is_cancelled() is False
    t.set()
    assert t.is_cancelled() is True
    assert bool(t) is True
    assert t[0] is True
    t.clear()
    assert t.is_cancelled() is False

def test_subscribe_and_emit():
    q = DownloadQueue()
    seen = []
    q.subscribe(lambda ev, data: seen.append((ev, data)))
    q.emit("hello", {"a": 1})
    assert seen and seen[0][0] == "hello"

def test_emit_wraps_non_dict():
    q = DownloadQueue()
    seen = []
    q.subscribe(lambda ev, data: seen.append(data))
    q.emit("x", "notadict")
    assert isinstance(seen[0], dict)

def test_statut_shape():
    q = DownloadQueue()
    s = q.statut()
    for key in ("en_cours", "queue", "historique", "elapsed", "en_pause"):
        assert key in s

def test_listener_exception_does_not_propagate():
    q = DownloadQueue()

    def bad(ev, data):
        raise RuntimeError("boom")

    q.subscribe(bad)
    q.emit("x", {})
