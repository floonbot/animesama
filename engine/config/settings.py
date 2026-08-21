
import json
import logging
import os
import sys
import threading
import time
from collections.abc import MutableMapping
from pathlib import Path
from typing import Final

log = logging.getLogger("engine.config.settings")

if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).parent
    _BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT_DIR)).resolve()
else:
    ROOT_DIR = Path(__file__).parent.parent.parent
    _BUNDLE_DIR = ROOT_DIR
def _resoudre_data_dir() -> Path:
    """ANIMESAMA_DATA_DIR deplace le dossier de donnees, tout entier.

    Les modules lient `DATA_DIR` a leur propre import (`COOKIES_FILE`,
    `DiskCache._dir`, `SETTINGS_FILE`...) : remplacer l'attribut apres coup ne
    les atteint plus. Le seul point ou la redirection porte sur tout le monde est
    donc ici, avant le premier import. C'est ce dont la suite de tests se sert
    pour ne pas ecrire dans les donnees reelles — voir tests/conftest.py.
    ROOT_DIR ne bouge pas : l'empreinte du trousseau en depend.
    """
    brut = os.getenv("ANIMESAMA_DATA_DIR", "").strip()
    return Path(brut).expanduser() if brut else ROOT_DIR / "data"


DATA_DIR = _resoudre_data_dir()
ENV_FILE = ROOT_DIR / ".env"

def _preparer_data_dir(d: Path) -> None:
    # Un mkdir nu ici tuait l'import du module, donc *tous* les points d'entree,
    # sur une installation en lecture seule. On degrade et on le dit.
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error(
            "Impossible de creer le dossier de donnees '%s' (%s) — reglages, profils "
            "et file d'attente ne seront pas sauvegardes. Verifie les droits en "
            "ecriture, ou lance l'application depuis un dossier accessible.", d, e,
        )
        return
    if os.name == "posix":
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass

_preparer_data_dir(DATA_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE, override=False)
except ImportError:
    pass

def _has_chromium_dir(browsers: Path) -> bool:
    try:
        return browsers.is_dir() and any(p.is_dir() for p in browsers.glob("chromium*"))
    except OSError:
        return False

def _configure_playwright_browsers_path(
    bundle_dir: Path, frozen: bool, environ: MutableMapping[str, str]
) -> str | None:
    if not frozen:
        return None
    browsers = Path(bundle_dir) / "ms-playwright"
    if not _has_chromium_dir(browsers):
        return None
    environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    return environ.get("PLAYWRIGHT_BROWSERS_PATH")

def bundled_chromium_present() -> bool:
    return _has_chromium_dir(_BUNDLE_DIR / "ms-playwright")

def _configure_bundled_bin_path(
    bundle_dir: Path, frozen: bool, environ: MutableMapping[str, str]
) -> bool:
    if not frozen:
        return False
    bindir = Path(bundle_dir) / "bin"
    try:
        if not bindir.is_dir():
            return False
    except OSError:
        return False
    bstr = str(bindir)
    current = environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if parts and parts[0] == bstr:
        return True
    parts = [p for p in parts if p and p != bstr]
    environ["PATH"] = os.pathsep.join([bstr, *parts])
    return True

_configure_playwright_browsers_path(_BUNDLE_DIR, getattr(sys, "frozen", False), os.environ)
_configure_bundled_bin_path(_BUNDLE_DIR, getattr(sys, "frozen", False), os.environ)

def _env_int(name: str, default: int, *, mini: int = 1, maxi: int = 65535) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        n = int(raw)
    except (TypeError, ValueError):
        log.warning(f"[settings] {name}={raw!r} invalide, utilisation de {default}")
        return default
    if not (mini <= n <= maxi):
        log.warning(f"[settings] {name}={n} hors limites [{mini};{maxi}], utilisation de {default}")
        return default
    return n

def _env_float(name: str, default: float, *, mini: float, maxi: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError):
        log.warning(f"[settings] {name}={raw!r} invalide, utilisation de {default}")
        return default
    if not (mini <= v <= maxi):
        log.warning(f"[settings] {name}={v} hors limites [{mini};{maxi}], utilisation de {default}")
        return default
    return v

_FAUX = ("0", "false", "no", "off")

def _env_bool(name: str, default: bool) -> bool:
    # « VAR= » veut dire « je n'ai rien choisi », pas « non » — c'est deja ce que
    # font _env_int et _env_float, qui retombent sur le defaut sur une valeur
    # illisible. Traiter le vide comme un « non » aurait coupe en silence
    # DL_ABANDON_LENT chez qui laisse la ligne sans valeur dans son .env.
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in _FAUX

def _safe_mkdir(p: Path, label: str) -> Path:
    try:
        p.mkdir(parents=True, exist_ok=True)
        return p
    except (OSError, PermissionError) as e:
        fallback = ROOT_DIR / "downloads"
        log.error(f"[settings] {label} '{p}' impossible ({e}) — fallback {fallback}")
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return fallback

HOST: Final = "127.0.0.1"
PORT = _env_int("PORT", 7843, mini=1, maxi=65535)

DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", str(ROOT_DIR / "downloads"))).expanduser()
STATIC_DIR    = _BUNDLE_DIR / "web" / "static"
DOWNLOADS_DIR = _safe_mkdir(DOWNLOADS_DIR, "DOWNLOADS_DIR")

SCANS_DIR = Path(os.getenv("SCANS_DIR", str(ROOT_DIR / "scans"))).expanduser()
SCANS_DIR = _safe_mkdir(SCANS_DIR, "SCANS_DIR")

DL_MAX_RETRIES = _env_int("DL_MAX_RETRIES", 1, mini=1, maxi=20)
DL_RETRY_DELAY = _env_int("DL_RETRY_DELAY", 3, mini=0, maxi=60)

DEBIT_ABANDON_ACTIF = _env_bool("DL_ABANDON_LENT", True)
DEBIT_PLANCHER_MO_S  = _env_float("DL_DEBIT_PLANCHER_MO_S", 0.8, mini=0.01, maxi=100.0)
DEBIT_PLAFOND_MO_S   = _env_float("DL_DEBIT_PLAFOND_MO_S", 3.0, mini=0.01, maxi=100.0)
DEBIT_FRACTION_REF   = _env_float("DL_DEBIT_FRACTION_REF", 0.25, mini=0.0, maxi=1.0)
DEBIT_DEMARRAGE_S    = _env_int("DL_DEBIT_DEMARRAGE_S", 25, mini=1, maxi=600)
DEBIT_FENETRE_S      = _env_int("DL_DEBIT_FENETRE_S", 45, mini=5, maxi=1800)
DEBIT_RESTE_MIN_S    = _env_int("DL_DEBIT_RESTE_MIN_S", 600, mini=30, maxi=14400)
DEBIT_MAX_ABANDONS   = _env_int("DL_DEBIT_MAX_ABANDONS", 2, mini=0, maxi=10)

# Le sniff tournait fenetre ouverte, et l'interception essaie jusqu'a quatre
# lecteurs en parallele : quatre fenetres Chromium surgissaient pendant un
# telechargement. Mesure du 11 aout 2026, 17 lecteurs x 3 configurations, meme
# echantillon et ordre tournant : 7/17 captures dans les trois cas, a la seconde
# pres — aucun lecteur ou le mode visible reussit la ou le headless echoue.
#
# Sans `channel`, headless=True lance chrome-headless-shell : un autre binaire,
# au fingerprint plus pauvre. « chromium » demande le vrai Chrome sans fenetre
# (le « new headless »), donc exactement l'executable du mode visible — on ne
# change que l'affichage, pas ce que l'hebergeur voit.
# BROWSER_HEADLESS=false rend les fenetres, BROWSER_CHANNEL="" reprend le shell.
# (La double negation d'avant faisait passer BROWSER_HEADLESS=0 pour un « oui ».)
BROWSER_HEADLESS         = _env_bool("BROWSER_HEADLESS", True)
BROWSER_CHANNEL          = os.getenv("BROWSER_CHANNEL", "chromium").strip()
BROWSER_PAGE_TIMEOUT_MS  = _env_int("BROWSER_PAGE_TIMEOUT_MS", 30_000, mini=5_000, maxi=120_000)

DOMAIN_MIN_DELAYS: dict[str, float] = {
    "video.sibnet.ru": 8.0,
    "sibnet.ru":       8.0,
    "sendvid.com":     5.0,
    "www.sendvid.com": 5.0,
    "vidmoly.to":      6.0,
    "www.vidmoly.to":  6.0,
    "vidmoly.net":     6.0,
    "vidmoly.biz":     6.0,
    "vidmoly.me":      6.0,
    "vk.com":          3.0,
    "ok.ru":           3.0,
    "oneupload.to":    5.0,
}
DOMAIN_MIN_DELAY_DEFAULT: float = 2.0

DOMAIN_PENALTY_DELAYS: dict[str, float] = {
    "video.sibnet.ru": 90.0,
    "sibnet.ru":       90.0,
    "sendvid.com":     60.0,
    "www.sendvid.com": 60.0,
    "vidmoly.to":      60.0,
    "www.vidmoly.to":  60.0,
    "vidmoly.net":     60.0,
    "vidmoly.biz":     60.0,
    "vidmoly.me":      60.0,
}
DOMAIN_PENALTY_DELAY_DEFAULT: float = 30.0

_domain_delays_json = os.getenv("DOMAIN_DELAYS_JSON", "")
if _domain_delays_json:
    try:
        DOMAIN_MIN_DELAYS.update(json.loads(_domain_delays_json))
        log.debug("[settings] DOMAIN_DELAYS_JSON chargé")
    except Exception as e:
        log.warning(f"[settings] DOMAIN_DELAYS_JSON invalide : {e}")

YTDLP_FIRST_DOMAINS: frozenset[str] = frozenset({
    "sendvid.com",    "www.sendvid.com",
    "vk.com",         "vkvideo.ru",
    "ok.ru",
    "myvi.ru",        "www.myvi.ru",
    "streamtape.com", "streamtape.net",
    "dood.watch",     "doodstream.com",
    "filemoon.sx",
})

_ytdlp_extra = os.getenv("YTDLP_EXTRA_DOMAINS", "")
if _ytdlp_extra:
    try:
        extras = json.loads(_ytdlp_extra)
        YTDLP_FIRST_DOMAINS = YTDLP_FIRST_DOMAINS | frozenset(extras)
        log.debug(f"[settings] {len(extras)} domaine(s) yt-dlp ajoutés depuis .env")
    except Exception as e:
        log.warning(f"[settings] YTDLP_EXTRA_DOMAINS invalide : {e}")

HOSTS_MORTS: frozenset[str] = frozenset({
    "oneupload.to", "oneupload.net", "oneupload.cc", "oneupload.stream",
})

_hosts_morts_extra = os.getenv("HOSTS_MORTS_EXTRA", "")
if _hosts_morts_extra:
    try:
        HOSTS_MORTS = HOSTS_MORTS | frozenset(json.loads(_hosts_morts_extra))
        log.debug("[settings] HOSTS_MORTS_EXTRA chargé")
    except Exception as e:
        log.warning(f"[settings] HOSTS_MORTS_EXTRA invalide : {e}")

HOST_DOMAIN_REWRITES: dict[str, str] = {
    "vidmoly.to": "vidmoly.net", "www.vidmoly.to": "vidmoly.net",
    "vidmoly.me": "vidmoly.net", "www.vidmoly.me": "vidmoly.net",
    "vidmoly.biz": "vidmoly.net", "www.vidmoly.biz": "vidmoly.net",
}

_host_rewrites_json = os.getenv("HOST_DOMAIN_REWRITES_JSON", "")
if _host_rewrites_json:
    try:
        _rw = json.loads(_host_rewrites_json)
        if isinstance(_rw, dict):
            HOST_DOMAIN_REWRITES.update({str(k).lower(): str(v) for k, v in _rw.items()})
    except Exception as e:
        log.warning(f"[settings] HOST_DOMAIN_REWRITES_JSON invalide : {e}")

VIDEO_EXTENSIONS: tuple[str, ...] = (".mp4", ".mkv", ".ts", ".webm")

_ALERTE_DOSSIER_TTL = 300.0

class _CachedDir:

    _TTL = 5.0

    def __init__(self, default: Path, key: str, label: str) -> None:
        self._default = default
        self._key = key
        self._label = label
        self._val: Path | None = None
        self._ts = 0.0
        self._lock = threading.Lock()
        self._alerte: str | None = None
        self._alerte_ts = 0.0

    def invalidate(self) -> None:
        with self._lock:
            self._val = None
            self._ts = 0.0

    def _signaler_bascule(self, custom: str, cause: Exception) -> None:
        # Le dossier configure vit souvent sur un partage reseau : box eteinte,
        # lettre de lecteur non montee. Retomber en silence sur le dossier par
        # defaut faisait atterrir les fichiers ailleurs, avec une librairie
        # d'apparence vide et aucune trace. On ne rale qu'une fois par episode
        # d'indisponibilite : get() est appele a chaque episode.
        maintenant = time.time()
        with self._lock:
            deja_dit = self._alerte == custom
            recent = (maintenant - self._alerte_ts) < _ALERTE_DOSSIER_TTL
            if deja_dit and recent:
                return
            self._alerte = custom
            self._alerte_ts = maintenant
        log.error(
            "Dossier %s inaccessible : « %s » (%s).\n"
            "→ Les fichiers vont atterrir dans « %s » a la place. Verifie que le "
            "disque ou le partage reseau est bien connecte, puis corrige le "
            "dossier dans les reglages.",
            self._label, custom, cause, self._default,
        )

    def _resoudre(self, custom: str) -> Path | None:
        p = Path(custom).expanduser()
        try:
            if p.is_dir():
                with self._lock:
                    self._alerte = None
                return p
            p.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as e:
            self._signaler_bascule(custom, e)
            return None
        log.info("Dossier %s recree : %s", self._label, p)
        with self._lock:
            self._alerte = None
        return p

    def get(self) -> Path:
        now = time.time()
        with self._lock:
            if self._val is not None and (now - self._ts) < self._TTL:
                return self._val
        result = self._default
        try:
            settings_file = DATA_DIR / "user_settings.json"
            if settings_file.exists():
                with open(settings_file, encoding="utf-8") as f:
                    data = json.load(f)
                raw = data.get(self._key) if isinstance(data, dict) else None
                custom = raw.strip() if isinstance(raw, str) else ""
                if custom:
                    result = self._resoudre(custom) or self._default
        except (OSError, json.JSONDecodeError) as e:
            log.warning("user_settings.json illisible (%s), dossier par defaut : %s", self._label, e)
        with self._lock:
            self._val = result
            self._ts = now
        return result

_downloads_dir = _CachedDir(DOWNLOADS_DIR, "downloads_dir", "downloads")
_scans_dir = _CachedDir(SCANS_DIR, "scans_dir", "scans")

def invalider_downloads_dir_cache() -> None:
    _downloads_dir.invalidate()

def get_downloads_dir() -> Path:
    return _downloads_dir.get()

def invalider_scans_dir_cache() -> None:
    _scans_dir.invalidate()

def get_scans_dir() -> Path:
    return _scans_dir.get()

DEFAULT_USER_AGENT: str = (
    os.getenv("USER_AGENT", "").strip().replace("\r", "").replace("\n", "").replace("\x00", "")
    or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

TAILLE_MIN_NM3U8DL  = 10 * 1024 * 1024
TAILLE_MIN_YTDLP    =  5 * 1024 * 1024
TAILLE_MIN_FFMPEG   =  2 * 1024 * 1024
