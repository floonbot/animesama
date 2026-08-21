import sqlite3

import pytest

from engine.cache import disk_cache
from engine.cache.disk_cache import DiskCache


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_cache, "DATA_DIR", tmp_path)
    return tmp_path


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_set_get_roundtrip_and_persists_to_disk(data_dir):
    c = DiskCache("rt", ttl=1000.0)
    c.set("k", {"v": 1})
    assert c.get("k") == {"v": 1}

    conn = sqlite3.connect(str(data_dir / "cache" / "rt.db"))
    payload = conn.execute("SELECT payload FROM cache WHERE key = 'k'").fetchone()[0]
    conn.close()
    assert payload == '{"v": 1}'


def test_value_survives_a_fresh_instance(data_dir):
    DiskCache("persist", ttl=1000.0).set("k", "value")
    assert DiskCache("persist", ttl=1000.0).get("k") == "value"


def test_get_expired_returns_none_and_evicts(data_dir, monkeypatch):
    clock = _Clock(1000.0)
    monkeypatch.setattr(disk_cache.time, "time", clock)
    c = DiskCache("exp", ttl=10.0)
    c.set("k", 42)
    assert c.get("k") == 42
    clock.t = 1011.0
    assert c.get("k") is None

    conn = sqlite3.connect(str(data_dir / "cache" / "exp.db"))
    reste = conn.execute("SELECT COUNT(*) FROM cache WHERE key = 'k'").fetchone()[0]
    conn.close()
    assert reste == 0


def test_malformed_stored_entry_returns_none(data_dir):
    c = DiskCache("mal", ttl=1000.0)
    c.set("bon", 1)

    conn = sqlite3.connect(str(data_dir / "cache" / "mal.db"))
    conn.execute(
        "INSERT OR REPLACE INTO cache (key, ts, payload) VALUES ('bad', ?, ?)",
        (disk_cache.time.time(), "{ceci n'est pas du json"),
    )
    conn.commit()
    conn.close()

    assert c.get("bad") is None
    assert c.get("bon") == 1


def test_corrupt_db_file_falls_back_to_empty(data_dir):
    path = data_dir / "cache" / "corrupt.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a database at all", encoding="utf-8")

    c = DiskCache("corrupt", ttl=1000.0)

    assert c.get("anything") is None
    c.set("neuf", 1)
    assert c.get("neuf") == 1


def test_nondict_json_file_is_ignored(data_dir):
    path = data_dir / "cache" / "list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    c = DiskCache("list", ttl=1000.0)

    assert c.get("x") is None
    assert not path.exists()


def test_capacity_eviction_drops_oldest(data_dir, monkeypatch):
    clock = _Clock(1000.0)
    monkeypatch.setattr(disk_cache.time, "time", clock)
    c = DiskCache("cap", ttl=10_000.0, cap=2)
    c.set("a", 1)
    clock.t += 1
    c.set("b", 2)
    clock.t += 1
    c.set("c", 3)

    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_set_many_empty_is_noop(data_dir):
    c = DiskCache("empty", ttl=1000.0)
    c.set_many({})
    assert not (data_dir / "cache" / "empty.db").exists()


def test_get_at_exact_ttl_is_expired(data_dir, monkeypatch):
    clock = _Clock(1000.0)
    monkeypatch.setattr(disk_cache.time, "time", clock)
    c = DiskCache("ttlbound", ttl=10.0)
    c.set("k", 1)
    clock.t = 1010.0
    assert c.get("k") is None


def test_ecriture_impossible_ne_leve_pas(data_dir, monkeypatch):
    c = DiskCache("ro", ttl=100.0)

    def _boom(*a, **k):
        raise OSError("cannot mkdir")

    monkeypatch.setattr(disk_cache.Path, "mkdir", _boom)

    c.set("k", "v")
    assert c.get("k") is None


def test_close_libere_la_connexion_sqlite(data_dir):
    """`pytest -W default` remontait « unclosed database » par instance."""
    c = DiskCache("ferme", ttl=1000.0)
    c.set("k", "v")
    assert c._conn is not None

    c.close()

    assert c._conn is None
    c.close()  # idempotent


def test_le_cache_se_rouvre_apres_fermeture(data_dir):
    c = DiskCache("rouvre", ttl=1000.0)
    c.set("k", "v")
    c.close()
    assert c.get("k") == "v"


def test_aucun_resource_warning_a_la_collecte(data_dir):
    import gc
    import warnings

    c = DiskCache("gc", ttl=1000.0)
    c.set("k", "v")
    with warnings.catch_warnings(record=True) as captes:
        warnings.simplefilter("always")
        del c
        gc.collect()
    assert [w for w in captes if issubclass(w.category, ResourceWarning)] == []
