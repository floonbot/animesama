import json
import sqlite3
import time

import pytest

import engine.cache.disk_cache as dc


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "DATA_DIR", tmp_path)
    return tmp_path / "cache"


def _fabriquer(cache_dir, name="episodes", ttl=3600.0, cap=300):
    return dc.DiskCache(name, ttl, cap)


def test_aller_retour(cache_dir):
    c = _fabriquer(cache_dir)

    c.set("a", {"episodes": [1, 2, 3]})

    assert c.get("a") == {"episodes": [1, 2, 3]}
    assert c.get("inconnu") is None


def test_expiration_par_ttl(cache_dir, monkeypatch):
    c = _fabriquer(cache_dir, ttl=10.0)
    c.set("a", "valeur")

    plus_tard = time.time() + 11
    monkeypatch.setattr(dc.time, "time", lambda: plus_tard)

    assert c.get("a") is None


def test_eviction_au_dela_du_cap(cache_dir):
    c = _fabriquer(cache_dir, cap=5)

    for i in range(12):
        c.set(f"k{i}", i)

    restants = [f"k{i}" for i in range(12) if c.get(f"k{i}") is not None]
    assert len(restants) <= 5
    assert "k11" in restants
    assert "k0" not in restants


def test_delete_et_clear(cache_dir):
    c = _fabriquer(cache_dir)
    c.set_many({"a": 1, "b": 2, "c": 3})

    c.delete("a", "b")
    assert c.get("a") is None
    assert c.get("c") == 3

    c.clear()
    assert c.get("c") is None


def test_import_depuis_un_json_existant(cache_dir):
    cache_dir.mkdir(parents=True)
    json_path = cache_dir / "episodes.json"
    json_path.write_text(
        json.dumps({"vieux": [time.time(), {"episodes": ["ep1"]}]}), encoding="utf-8"
    )

    c = _fabriquer(cache_dir)

    assert c.get("vieux") == {"episodes": ["ep1"]}
    assert not json_path.exists()


def test_json_corrompu_donne_un_cache_vide_sans_exception(cache_dir):
    cache_dir.mkdir(parents=True)
    json_path = cache_dir / "episodes.json"
    json_path.write_text("{ceci n'est pas du json", encoding="utf-8")

    c = _fabriquer(cache_dir)

    assert c.get("quoi que ce soit") is None
    c.set("neuf", 1)
    assert c.get("neuf") == 1


def test_base_corrompue_est_mise_en_quarantaine(cache_dir):
    cache_dir.mkdir(parents=True)
    db = cache_dir / "episodes.db"
    db.write_bytes(b"ceci n'est pas une base sqlite" * 10)

    c = _fabriquer(cache_dir)

    c.set("a", 1)
    assert c.get("a") == 1
    assert list(cache_dir.glob("episodes.db.corrupt*"))


def test_une_ecriture_ne_reecrit_pas_les_autres_entrees(cache_dir):
    c = _fabriquer(cache_dir)
    c.set_many({f"k{i}": {"episodes": list(range(50))} for i in range(100)})

    chemin = cache_dir / "episodes.db"
    conn = sqlite3.connect(str(chemin))
    avant = {
        k: v for k, v in conn.execute("SELECT key, payload FROM cache WHERE key != 'nouveau'")
    }
    conn.close()

    c.set("nouveau", {"episodes": [1]})

    conn = sqlite3.connect(str(chemin))
    apres = {
        k: v for k, v in conn.execute("SELECT key, payload FROM cache WHERE key != 'nouveau'")
    }
    conn.close()

    assert apres == avant
    assert c.get("nouveau") == {"episodes": [1]}


def test_les_expires_sont_purges_a_l_ouverture(cache_dir):
    c = _fabriquer(cache_dir, ttl=1.0)
    c.set("perime", "x")

    conn = sqlite3.connect(str(cache_dir / "episodes.db"))
    conn.execute("UPDATE cache SET ts = ?", (time.time() - 100,))
    conn.commit()
    conn.close()

    c2 = _fabriquer(cache_dir, ttl=1.0)
    assert c2.get("perime") is None

    conn = sqlite3.connect(str(cache_dir / "episodes.db"))
    n = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    conn.close()
    assert n == 0


def test_les_appelants_existants_ne_changent_pas():
    import inspect

    sig = inspect.signature(dc.DiskCache.__init__)

    assert list(sig.parameters) == ["self", "name", "ttl", "cap"]
    assert sig.parameters["cap"].default == 300
    for methode in ("get", "set", "set_many", "delete", "clear"):
        assert callable(getattr(dc.DiskCache, methode))
