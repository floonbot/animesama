import sqlite3

from engine.download.store import DownloadStore


def _make_logically_corrupt_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE queue (pos INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO queue (pos, payload) VALUES (?, ?)",
        [(i, "x" * 500) for i in range(400)],
    )
    conn.commit()
    conn.close()

    data = bytearray(path.read_bytes())
    for off in range(4096 * 3, 4096 * 9):
        if off < len(data):
            data[off] ^= 0xFF
    path.write_bytes(data)


def _is_genuinely_corrupt(path):
    probe = sqlite3.connect(str(path))
    try:
        return probe.execute("PRAGMA quick_check").fetchone()[0] != "ok"
    except sqlite3.DatabaseError:
        return True
    finally:
        probe.close()


def test_logically_corrupt_db_is_quarantined_not_silently_emptied(tmp_path):
    db = tmp_path / "downloads.db"
    _make_logically_corrupt_db(db)

    assert _is_genuinely_corrupt(db), "precondition: the DB must be genuinely corrupt"

    store = DownloadStore(db)
    try:
        assert (tmp_path / "downloads.db.corrupt").exists()
        assert store.load_queue() == []
    finally:
        store.close()
