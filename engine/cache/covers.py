import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger("engine.cache.covers")

COVERS_MAX_ENTRIES = 5000

_covers_lock_thread = threading.Lock()

def _covers_file() -> Path:
    from engine.config.settings import DATA_DIR
    return DATA_DIR / "covers.json"

def _load_covers() -> dict:
    try:
        f = _covers_file()
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if len(data) > COVERS_MAX_ENTRIES:
                    log.warning(
                        f"fichier trop gros ({len(data)} entrées), "
                        f"tronqué à {COVERS_MAX_ENTRIES}"
                    )
                    items = list(data.items())[-COVERS_MAX_ENTRIES:]
                    return dict(items)
                return data
            log.warning("fichier corrompu (pas un dict)")
    except Exception as e:
        log.warning(f"_load_covers : {e}")
    return {}

def _save_covers(covers: dict) -> bool:
    try:
        f = _covers_file()
        tmp = f.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(covers, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, f)
        return True
    except Exception as e:
        log.warning(f"_save_covers : {e}")
        return False

_covers_cache: dict[str, str] = _load_covers()
