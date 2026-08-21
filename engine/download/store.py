import json
import logging
import os
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

log = logging.getLogger("engine.download.store")

def _metric_write_error() -> None:
    try:
        from engine.observability.metrics import metrics
        metrics.incr("store_write_error")
    except Exception:
        pass

def _metric_read_error() -> None:
    try:
        from engine.observability.metrics import metrics
        metrics.incr("store_read_error")
    except Exception:
        pass

class DownloadStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from engine.config.settings import DATA_DIR
            path = DATA_DIR / "downloads.db"
        self._path = Path(path)
        self._lock = threading.Lock()
        self._closed = False
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dl_store")
        self._conn = self._connect(self._path)

    def _connect(self, path: Path) -> sqlite3.Connection:
        try:
            return self._open(path)
        except sqlite3.DatabaseError:
            log.error("downloads.db illisible/corrompu — mise à l'écart et recréation", exc_info=True)
            self._quarantine(path)
            return self._open(path)

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS queue (pos INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS history "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS current "
                "(id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)"
            )
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
    def _quarantine(path: Path) -> None:
        cible = path.with_name(path.name + ".corrupt")
        n = 1
        while cible.exists():
            cible = path.with_name(f"{path.name}.corrupt-{n}")
            n += 1
        try:
            os.replace(str(path), str(cible))
        except OSError:
            log.warning("impossible de mettre à l'écart %s", path, exc_info=True)
            return
        for suffixe in ("-wal", "-shm"):
            annexe = path.with_name(path.name + suffixe)
            try:
                if annexe.exists():
                    os.remove(str(annexe))
            except OSError:
                log.debug("nettoyage annexe %s impossible", annexe, exc_info=True)

    @staticmethod
    def _log_writer_error(fut) -> None:
        exc = fut.exception()
        if exc is not None:
            log.warning("store write failed", exc_info=exc)
            _metric_write_error()

    def _submit(self, fn, *args) -> None:
        if self._closed:
            return
        try:
            self._writer.submit(fn, *args).add_done_callback(self._log_writer_error)
        except RuntimeError:
            pass

    def _flush(self) -> None:
        try:
            self._writer.submit(lambda: None).result(timeout=10)
        except Exception:
            pass

    def _write(self, op_name: str, fn: Callable[[], None]) -> None:
        try:
            with self._lock:
                fn()
                self._conn.commit()
        except sqlite3.Error:
            try:
                with self._lock:
                    self._conn.rollback()
            except Exception:
                pass
            log.warning(f"{op_name} failed", exc_info=True)
            _metric_write_error()

    @staticmethod
    def _decode_dict_rows(rows: list) -> list[dict]:
        out = []
        for (payload,) in rows:
            try:
                obj = json.loads(payload)
                if isinstance(obj, dict):
                    out.append(obj)
            except (TypeError, ValueError):
                continue
        return out

    def save_queue(self, items: list[dict[str, Any]]) -> None:
        rows = []
        for i, it in enumerate(items):
            try:
                rows.append((i, json.dumps(it)))
            except (TypeError, ValueError):
                continue
        self._submit(self._save_queue_sync, rows)

    def _save_queue_sync(self, rows: list[tuple[int, str]]) -> None:
        def op() -> None:
            self._conn.execute("DELETE FROM queue")
            self._conn.executemany("INSERT INTO queue (pos, payload) VALUES (?, ?)", rows)
        self._write("save_queue", op)

    def load_queue(self) -> list[dict]:
        self._flush()
        try:
            with self._lock:
                rows = self._conn.execute("SELECT payload FROM queue ORDER BY pos").fetchall()
        except sqlite3.Error:
            log.warning("load_queue failed", exc_info=True)
            _metric_read_error()
            return []
        return self._decode_dict_rows(rows)

    def append_history(self, entry: dict, cap: int = 200) -> None:
        try:
            payload = json.dumps(entry)
        except (TypeError, ValueError):
            return
        self._submit(self._append_history_sync, payload, cap)

    def _append_history_sync(self, payload: str, cap: int = 200) -> None:
        def op() -> None:
            self._conn.execute("INSERT INTO history (payload) VALUES (?)", (payload,))
            self._conn.execute(
                "DELETE FROM history WHERE id NOT IN "
                "(SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                (cap,),
            )
        self._write("append_history", op)

    def clear_history(self) -> None:
        self._submit(self._clear_history_sync)

    def _clear_history_sync(self) -> None:
        # Les lignes ecrites avant la suppression du multi-profils portent encore
        # un `profile_id` dans leur payload JSON : il n'est plus ni lu ni ecrit,
        # et ce DELETE les emporte comme les autres.
        def op() -> None:
            self._conn.execute("DELETE FROM history")
        self._write("clear_history", op)

    def load_history(self, cap: int = 200) -> list[dict]:
        self._flush()
        try:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT payload FROM (SELECT id, payload FROM history ORDER BY id DESC LIMIT ?) "
                    "ORDER BY id ASC",
                    (cap,),
                ).fetchall()
        except sqlite3.Error:
            log.warning("load_history failed", exc_info=True)
            _metric_read_error()
            return []
        return self._decode_dict_rows(rows)

    def save_current(self, item: dict) -> None:
        try:
            payload = json.dumps(item)
        except (TypeError, ValueError):
            return
        self._submit(self._save_current_sync, payload)

    def save_current_sync(self, item: dict) -> None:
        try:
            payload = json.dumps(item)
        except (TypeError, ValueError):
            return
        self._save_current_sync(payload)

    def _save_current_sync(self, payload: str) -> None:
        def op() -> None:
            self._conn.execute("DELETE FROM current")
            self._conn.execute("INSERT INTO current (id, payload) VALUES (1, ?)", (payload,))
        self._write("save_current", op)

    def clear_current(self) -> None:
        self._submit(self._clear_current_sync)

    def clear_current_sync(self) -> None:
        self._clear_current_sync()

    def _clear_current_sync(self) -> None:
        def op() -> None:
            self._conn.execute("DELETE FROM current")
        self._write("clear_current", op)

    def load_current(self) -> dict | None:
        self._flush()
        try:
            with self._lock:
                row = self._conn.execute("SELECT payload FROM current WHERE id = 1").fetchone()
        except sqlite3.Error:
            log.warning("load_current failed", exc_info=True)
            _metric_read_error()
            return None
        if not row:
            return None
        try:
            obj = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        return obj if isinstance(obj, dict) else None

    def close(self) -> None:
        self._closed = True
        try:
            self._writer.shutdown(wait=True)
        except Exception:
            pass
        try:
            with self._lock:
                self._conn.close()
        except sqlite3.Error:
            pass

    def __del__(self) -> None:
        # Meme filet que DiskCache : le magasin de l'application vit aussi
        # longtemps que le processus, mais les tests en creent un par cas et le
        # laissent au ramasse-miettes. `close()` est idempotent.
        try:
            self.close()
        except Exception:
            pass
