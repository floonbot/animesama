import json
import logging
import os
import threading

from engine.config._quarantaine import mettre_a_lecart
from engine.config.settings import DATA_DIR

log = logging.getLogger("engine.config.user_settings")

SETTINGS_FILE = DATA_DIR / "user_settings.json"

_save_lock = threading.Lock()


def _target():
    return SETTINGS_FILE

QUALITES_VALIDES = {"auto", "1080", "720", "480"}

DEFAULT_SETTINGS = {
    "qualite":       "auto",
    "thread_count":  16,
    "downloads_dir": "",
    "scans_dir":     "",
    "notifications": True,
    "son_notif":     True,
    "confirm_suppr": True,
    "skip_existants": True,
    "langue_defaut": "VOSTFR",
    # Veille des nouveaux episodes (engine/library/veille.py)
    "veille_nouveautes":   True,
    "veille_intervalle_h": 6,
    "veille_auto_dl":      False,
}

def load_settings() -> dict:
    target = _target()
    if target.exists():
        try:
            with open(target, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            # Sans mise a l'ecart, le prochain save_settings ecrasait un fichier
            # peut-etre reparable par les valeurs par defaut.
            mettre_a_lecart(target, f"JSON invalide : {e}")
            return dict(DEFAULT_SETTINGS)
        except OSError as e:
            log.warning(f"lecture impossible : {e}")
            return dict(DEFAULT_SETTINGS)
        if not isinstance(data, dict):
            mettre_a_lecart(target, f"contenu inattendu ({type(data).__name__} au lieu d'un objet)")
            return dict(DEFAULT_SETTINGS)
        return {**DEFAULT_SETTINGS, **data}
    return dict(DEFAULT_SETTINGS)

def save_settings(s: dict) -> bool:
    target = _target()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        with _save_lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2, ensure_ascii=False)
            try:
                # Quasi no-op sous Windows (ne bascule que le flag lecture seule) :
                # la protection de data/ repose sur les ACL par defaut du profil.
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, target)
        return True
    except OSError as e:
        log.error(f"écriture impossible : {e}")
        return False
