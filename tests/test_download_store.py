from engine.download.store import DownloadStore


def test_queue_roundtrip(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    items = [{"nom": "A", "episodes": [1, 2]}, {"_direct": True, "url_stream": "x"}]
    s.save_queue(items)
    assert s.load_queue() == items
    s.close()

def test_queue_replace(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    s.save_queue([{"a": 1}, {"b": 2}])
    s.save_queue([{"c": 3}])
    assert s.load_queue() == [{"c": 3}]
    s.close()

def test_queue_persists_across_instances(tmp_path):
    p = tmp_path / "d.db"
    s = DownloadStore(p)
    s.save_queue([{"keep": True}])
    s.close()
    s2 = DownloadStore(p)
    assert s2.load_queue() == [{"keep": True}]
    s2.close()

def test_history_append_and_cap(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    for i in range(10):
        s.append_history({"i": i}, cap=5)
    hist = s.load_history()
    assert [h["i"] for h in hist] == [5, 6, 7, 8, 9]
    s.close()

def test_non_serialisable_is_skipped(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    s.save_queue([{"ok": 1}, {"bad": object()}])
    assert s.load_queue() == [{"ok": 1}]
    s.close()
