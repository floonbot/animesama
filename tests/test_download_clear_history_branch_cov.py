WRITE_HEADERS = {"origin": "http://localhost:7843"}

def test_store_clear_history_vide_la_table(tmp_path):
    from engine.download.store import DownloadStore

    st = DownloadStore(tmp_path / "downloads.db")
    try:
        st.append_history({"titre": "A", "langue": "vf"})
        st.append_history({"titre": "B", "langue": "vostfr"})
        assert len(st.load_history()) == 2

        st.clear_history()

        assert st.load_history() == []
    finally:
        st.close()

def test_store_clear_history_emporte_les_lignes_a_ancien_profile_id(tmp_path):
    """Les lignes ecrites avant la suppression du multi-profils portent encore
    un profile_id dans leur payload : le DELETE doit les emporter aussi."""
    from engine.download.store import DownloadStore

    st = DownloadStore(tmp_path / "downloads.db")
    try:
        st.append_history({"titre": "Legacy", "langue": "vf", "profile_id": "kids"})
        st.append_history({"titre": "Neuf", "langue": "vf"})
        assert len(st.load_history()) == 2

        st.clear_history()

        assert st.load_history() == []
    finally:
        st.close()

def test_queue_clear_history_vide_tout_et_emet(tmp_path):
    from engine.download.queue import DownloadQueue
    from engine.download.store import DownloadStore

    q = DownloadQueue()
    q._store = DownloadStore(tmp_path / "downloads.db")
    try:
        a = {"titre": "A", "langue": "vf"}
        b = {"titre": "B", "langue": "vf", "profile_id": "kids"}
        q._history = [dict(a), dict(b)]
        q._store.append_history(a)
        q._store.append_history(b)

        events = []
        q.subscribe(lambda ev, data: events.append(ev))

        q.clear_history()

        assert q._history == []
        assert q._store.load_history() == []
        assert "queue_updated" in events
    finally:
        q._store.close()

def test_service_vider_historique_delegates():
    from engine.download.queue import DownloadQueue
    from engine.services.download_service import DownloadService

    svc = DownloadService()
    q = DownloadQueue()
    q._history = [{"titre": "A"}]
    svc._queue = q

    res = svc.vider_historique()

    assert res == {"ok": True}
    assert q._history == []

def test_route_historique_clear_wires_service(client, monkeypatch):
    from engine.services.download_service import download_service

    called = {}

    def fake():
        called["hit"] = True
        return {"ok": True}

    monkeypatch.setattr(download_service, "vider_historique", fake)

    r = client.post("/api/download/historique/clear", headers=WRITE_HEADERS)

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert called.get("hit") is True
