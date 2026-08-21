import sqlite3

import pytest

from engine.download.store import DownloadStore


def test_corrupt_db_is_quarantined_and_recreated(tmp_path):
    db = tmp_path / "downloads.db"
    db.write_bytes(b"this is not a sqlite database\x00" * 200)

    store = DownloadStore(db)
    try:
        store.save_queue([{"nom": "A"}])
        store._flush()
        assert store.load_queue() == [{"nom": "A"}]
        assert (tmp_path / "downloads.db.corrupt").exists()
    finally:
        store.close()


def test_valid_db_is_not_quarantined(tmp_path):
    db = tmp_path / "downloads.db"
    s1 = DownloadStore(db)
    s1.save_current({"nom": "A"})
    s1._flush()
    s1.close()

    s2 = DownloadStore(db)
    try:
        assert s2.load_current() == {"nom": "A"}
        assert not (tmp_path / "downloads.db.corrupt").exists()
    finally:
        s2.close()


def test_second_corruption_uses_distinct_quarantine_name(tmp_path):
    db = tmp_path / "downloads.db"
    (tmp_path / "downloads.db.corrupt").write_bytes(b"older corpse")
    db.write_bytes(b"not sqlite either\x00" * 200)

    store = DownloadStore(db)
    try:
        store.save_queue([{"nom": "B"}])
        store._flush()
        assert store.load_queue() == [{"nom": "B"}]
        assert (tmp_path / "downloads.db.corrupt").read_bytes() == b"older corpse"
        assert (tmp_path / "downloads.db.corrupt-1").exists()
    finally:
        store.close()


def test_unrecoverable_corruption_raises_for_graceful_degradation(tmp_path, monkeypatch):
    db = tmp_path / "downloads.db"
    db.write_bytes(b"garbage\x00" * 200)

    def _no_quarantine(self, path):
        return None

    monkeypatch.setattr(DownloadStore, "_quarantine", _no_quarantine)

    with pytest.raises(sqlite3.DatabaseError):
        DownloadStore(db)
