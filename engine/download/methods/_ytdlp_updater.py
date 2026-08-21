import logging
import os
import re
import subprocess
import sys
import threading
from datetime import UTC, datetime

log = logging.getLogger("engine.download.ytdlp_updater")

_LATEST_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
_LATEST_TAG_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest"
_MAX_AGE_DAYS = 14
_MIN_EXE_BYTES = 1_000_000
_RE_TAG = re.compile(r"\d{4}\.\d{2}\.\d{2}")


def _desactive() -> bool:
    if getattr(sys, "frozen", False):
        return True
    if os.getenv("ANIMESAMA_NO_YTDLP_UPDATE", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    if "pytest" in sys.modules:
        return True
    return False


def _version_date(exe: str) -> datetime | None:
    try:
        from engine.download._engine_utils import NO_WINDOW_FLAGS, clean_subprocess_env
        out = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=15,
            env=clean_subprocess_env(), creationflags=NO_WINDOW_FLAGS,
        ).stdout.strip()
    except Exception:
        return None
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", out)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
    except ValueError:
        return None


def _age_jours(released: datetime) -> float:
    return (datetime.now(UTC) - released).total_seconds() / 86_400.0


def _gere_ce_binaire(exe: str) -> bool:
    return exe.replace("\\", "/").lower().endswith("/bin/yt-dlp.exe")


def _tag_distant() -> str | None:
    """Tag de la derniere release, lu dans la redirection de /releases/latest.

    L'age seul ne suffit pas : quand upstream ne publie rien pendant plus de
    _MAX_AGE_DAYS, l'app retelechargeait le meme binaire a chaque demarrage.
    """
    import requests
    try:
        r = requests.head(_LATEST_TAG_URL, timeout=15, allow_redirects=False)
        cible = r.headers.get("Location") or ""
    except Exception:
        log.debug("yt-dlp update : tag distant illisible", exc_info=True)
        return None
    tag = cible.rstrip("/").rsplit("/", 1)[-1]
    return tag if _RE_TAG.fullmatch(tag) else None


def _telecharger_latest(dest: str) -> bool:
    import requests
    tmp = dest + ".new"
    try:
        with requests.get(_LATEST_URL, timeout=180, stream=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(tmp) < _MIN_EXE_BYTES:
            raise RuntimeError("fichier telecharge trop petit")
        if _version_date(tmp) is None:
            raise RuntimeError("binaire telecharge illisible")
        os.replace(tmp, dest)
        return True
    except Exception:
        log.debug("yt-dlp update : telechargement echoue", exc_info=True)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def verifier_et_mettre_a_jour() -> None:
    if _desactive():
        return
    try:
        from engine.download.methods.ytdlp_engine import _get_ytdlp_path
        exe = _get_ytdlp_path()
    except Exception:
        return
    if not exe or not _gere_ce_binaire(exe):
        return
    released = _version_date(exe)
    if released is None:
        return
    age = _age_jours(released)
    if age < _MAX_AGE_DAYS:
        log.debug("yt-dlp a jour (%.0f jours)", age)
        return
    tag = _tag_distant()
    if tag is not None and tag == released.strftime("%Y.%m.%d"):
        log.debug("yt-dlp deja a la derniere version publiee (%s)", tag)
        return
    log.info("yt-dlp date de %.0f jours — mise a jour vers la derniere version...", age)
    if _telecharger_latest(exe):
        maj = _version_date(exe)
        log.info("yt-dlp mis a jour%s", f" ({maj.date()})" if maj else "")
    else:
        log.warning("yt-dlp : mise a jour impossible (reseau ?) — version actuelle conservee")


def demarrer_verification_ytdlp() -> None:
    threading.Thread(target=verifier_et_mettre_a_jour, daemon=True, name="ytdlp-update").start()
