import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from engine.config.settings import DATA_DIR

log = logging.getLogger("engine.cache.disk_cache")

class DiskCache:
    def __init__(self, name: str, ttl: float, cap: int = 300, version: str = "") -> None:
        self._ttl = ttl
        self._cap = cap
        self._dir = DATA_DIR / "cache"
        self._path = self._dir / f"{name}.db"
        self._json_path = self._dir / f"{name}.json"
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        # Une entree depend souvent du code qui l'a produite. Changer `version`
        # rend invisibles d'un coup les entrees de l'ancien code : elles
        # expirent ensuite d'elles-memes, sans fichier orphelin a nettoyer.
        self._prefixe = f"{version}|" if version else ""

    def _cle(self, key: str) -> str:
        return self._prefixe + key

    def _connexion(self) -> sqlite3.Connection | None:
        if self._conn is not None:
            return self._conn
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.debug("cache dir indisponible (%s) : %s", self._path.name, e)
            return None
        try:
            self._conn = self._ouvrir(self._path)
        except sqlite3.DatabaseError:
            log.warning("%s illisible — mise à l'écart et recréation", self._path.name)
            self._quarantaine(self._path)
            try:
                self._conn = self._ouvrir(self._path)
            except sqlite3.DatabaseError:
                log.warning("cache %s indisponible, fonctionnement sans", self._path.name)
                return None
        self._importer_json()
        self._purger_expires()
        return self._conn

    @staticmethod
    def _ouvrir(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache "
                "(key TEXT PRIMARY KEY, ts REAL NOT NULL, payload TEXT NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_ts ON cache(ts)")
            conn.commit()
            row = conn.execute("PRAGMA quick_check").fetchone()
            if not row or row[0] != "ok":
                raise sqlite3.DatabaseError(f"quick_check: {row[0] if row else 'no result'}")
        except sqlite3.DatabaseError:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            raise
        return conn

    @staticmethod
    def _quarantaine(path: Path) -> None:
        cible = path.with_name(path.name + ".corrupt")
        n = 1
        while cible.exists():
            cible = path.with_name(f"{path.name}.corrupt-{n}")
            n += 1
        try:
            os.replace(str(path), str(cible))
        except OSError:
            log.warning("impossible de mettre à l'écart %s", path.name)
            return
        for suffixe in ("-wal", "-shm"):
            annexe = path.with_name(path.name + suffixe)
            try:
                if annexe.exists():
                    annexe.unlink()
            except OSError:
                pass

    def _importer_json(self) -> None:
        if self._conn is None or not self._json_path.exists():
            return
        try:
            with open(self._json_path, encoding="utf-8") as f:
                charge = json.load(f)
            if isinstance(charge, dict):
                lignes = [
                    (k, float(v[0]), json.dumps(v[1]))
                    for k, v in charge.items()
                    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (int, float))
                ]
                if lignes:
                    self._conn.executemany(
                        "INSERT OR REPLACE INTO cache (key, ts, payload) VALUES (?, ?, ?)", lignes
                    )
                    self._conn.commit()
                log.info("cache %s : %d entrée(s) importée(s) du JSON", self._path.name, len(lignes))
        except (OSError, ValueError, TypeError, sqlite3.DatabaseError) as e:
            log.debug("import JSON ignoré (%s) : %s", self._json_path.name, e)
        try:
            self._json_path.unlink()
        except OSError:
            pass

    def _purger_expires(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute("DELETE FROM cache WHERE ts < ?", (time.time() - self._ttl,))
            self._conn.commit()
        except sqlite3.DatabaseError as e:
            log.debug("purge des expirés impossible (%s) : %s", self._path.name, e)

    def _evincer(self) -> None:
        if self._conn is None:
            return
        try:
            total = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            if total <= self._cap:
                return
            self._conn.execute(
                "DELETE FROM cache WHERE key IN "
                "(SELECT key FROM cache ORDER BY ts LIMIT ?)",
                (total - self._cap,),
            )
            self._conn.commit()
        except sqlite3.DatabaseError as e:
            log.debug("éviction impossible (%s) : %s", self._path.name, e)

    def get(self, key: str):
        key = self._cle(key)
        with self._lock:
            conn = self._connexion()
            if conn is None:
                return None
            try:
                row = conn.execute(
                    "SELECT ts, payload FROM cache WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.DatabaseError as e:
                log.debug("lecture cache impossible (%s) : %s", self._path.name, e)
                return None
            if row is None:
                return None
            # SQLite a un typage dynamique : un ts non numerique peut avoir ete insere.
            perime = not isinstance(row[0], (int, float)) or (time.time() - row[0]) >= self._ttl
            if perime:
                try:
                    conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                    conn.commit()
                except sqlite3.DatabaseError:
                    pass
                return None
            try:
                return json.loads(row[1])
            except ValueError:
                return None

    def set(self, key: str, value) -> None:
        self.set_many({key: value})

    def set_many(self, items: dict) -> None:
        if not items:
            return
        with self._lock:
            conn = self._connexion()
            if conn is None:
                return
            now = time.time()
            try:
                lignes = [(self._cle(k), now, json.dumps(v)) for k, v in items.items()]
            except (TypeError, ValueError) as e:
                log.debug("valeur non sérialisable ignorée (%s) : %s", self._path.name, e)
                return
            try:
                conn.executemany(
                    "INSERT OR REPLACE INTO cache (key, ts, payload) VALUES (?, ?, ?)", lignes
                )
                conn.commit()
            except sqlite3.DatabaseError as e:
                log.debug("écriture cache impossible (%s) : %s", self._path.name, e)
                return
            self._evincer()

    def delete(self, *keys: str) -> None:
        if not keys:
            return
        with self._lock:
            conn = self._connexion()
            if conn is None:
                return
            try:
                conn.executemany(
                    "DELETE FROM cache WHERE key = ?", [(self._cle(k),) for k in keys]
                )
                conn.commit()
            except sqlite3.DatabaseError as e:
                log.debug("suppression cache impossible (%s) : %s", self._path.name, e)

    def clear(self) -> None:
        with self._lock:
            conn = self._connexion()
            if conn is None:
                return
            try:
                conn.execute("DELETE FROM cache")
                conn.commit()
            except sqlite3.DatabaseError as e:
                log.debug("vidage cache impossible (%s) : %s", self._path.name, e)

    def close(self) -> None:
        """Ferme la connexion SQLite.

        Sans cela, `pytest -W default` remontait un ResourceWarning « unclosed
        database » par instance : les trois caches de l'application vivent aussi
        longtemps que le processus, mais les tests en creent un par cas.
        """
        with self._lock:
            conn, self._conn = self._conn, None
            if conn is None:
                return
            try:
                conn.close()
            except sqlite3.Error:
                log.debug("fermeture cache %s impossible", self._path.name, exc_info=True)

    def __del__(self) -> None:
        # Filet pour les instances jetables : le GC ne doit pas laisser fuir un
        # descripteur de fichier. `close()` est idempotent.
        try:
            self.close()
        except Exception:
            pass
