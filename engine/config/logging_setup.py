
import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler

from engine.observability.context import get_task_id
from engine.observability.redact import redact_text

if sys.stdout is None or sys.stderr is None:
    _sink = open(
        os.path.join(tempfile.gettempdir(), "anime_sama_desktop.log"),
        "a", encoding="utf-8", errors="replace",
    )
    if sys.stdout is None:
        sys.stdout = _sink
    if sys.stderr is None:
        sys.stderr = _sink

def _ensure_utf8_stdio() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

_ensure_utf8_stdio()

def _supports_color() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True

_COLOR_OK = _supports_color()

class C:
    if _COLOR_OK:
        RESET   = "\033[0m"
        DIM     = "\033[2m"
        BOLD    = "\033[1m"
        RED     = "\033[31m"
        GREEN   = "\033[32m"
        YELLOW  = "\033[33m"
        BLUE    = "\033[34m"
        MAGENTA = "\033[35m"
        CYAN    = "\033[36m"
        GRAY    = "\033[90m"
    else:
        RESET = DIM = BOLD = ""
        RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = GRAY = ""

SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "OK")

def _log_success(self, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS_LEVEL):
        self._log(SUCCESS_LEVEL, message, args, **kwargs)

logging.Logger.success = _log_success  # type: ignore[attr-defined]

_LEVEL_STYLES = {
    "DEBUG":    (C.GRAY,            "·", "DEBUG"),
    "INFO":     (C.CYAN,            "ℹ", "INFO "),
    "OK":       (C.GREEN,           "✓", "OK   "),
    "WARNING":  (C.YELLOW,          "⚠", "WARN "),
    "ERROR":    (C.RED,             "✗", "ERROR"),
    "CRITICAL": (C.RED + C.BOLD,    "‼", "CRIT "),
}

def _shorten_name(name: str, width: int = 14) -> str:
    short = name.rsplit(".", 1)[-1] if "." in name else name
    if len(short) > width:
        short = short[: width - 1] + "…"
    return short.ljust(width)

class CleanFormatter(logging.Formatter):

    def formatException(self, ei) -> str:
        return redact_text(super().formatException(ei))

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")

        color, sym, label = _LEVEL_STYLES.get(
            record.levelname, ("", "•", record.levelname.ljust(5))
        )

        short = _shorten_name(record.name)

        msg = redact_text(record.getMessage())
        if record.exc_info:
            msg = msg + "\n" + self.formatException(record.exc_info)

        tid = get_task_id()
        tid_seg = f"{C.DIM}[{tid}]{C.RESET} " if tid else ""

        return (
            f"{C.GRAY}{ts}{C.RESET}  "
            f"{color}{sym} {label}{C.RESET}  "
            f"{C.DIM}{short}{C.RESET}  "
            f"{tid_seg}{msg}"
        )

_NOISE_TYPES = {
    "TargetClosedError",
    "CancelledError",
}

_NOISE_PATTERNS = (
    "Target page, context or browser has been closed",
    "Target closed",
    "Browser has been closed",
)

class _AsyncioNoiseFilter(logging.Filter):

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()

        if "Future exception was never retrieved" not in msg:
            return True

        if record.exc_info and record.exc_info[1] is not None:
            exc_type_name = type(record.exc_info[1]).__name__
            if exc_type_name in _NOISE_TYPES:
                return False
            for cls in type(record.exc_info[1]).__mro__:
                if cls.__name__ in _NOISE_TYPES:
                    return False

        if "TargetClosedError" in msg or "CancelledError" in msg:
            return False
        for pat in _NOISE_PATTERNS:
            if pat in msg:
                return False

        return True

_QUIET_MODULES = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "fastapi",
    "asyncio",
    "urllib3",
    "urllib3.connectionpool",
    "playwright",
    "httpx",
    "httpcore",
)

def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(CleanFormatter())

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    from engine.observability.log_ring import install as _install_log_ring
    _install_log_ring()
    root.setLevel(level)

    for name in _QUIET_MODULES:
        logging.getLogger(name).setLevel(logging.WARNING)

    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.filters = [
        f for f in asyncio_logger.filters
        if not isinstance(f, _AsyncioNoiseFilter)
    ]
    asyncio_logger.addFilter(_AsyncioNoiseFilter())

    handler.filters = [
        f for f in handler.filters
        if not isinstance(f, _AsyncioNoiseFilter)
    ]
    handler.addFilter(_AsyncioNoiseFilter())

class _AppFileHandler(RotatingFileHandler):
    pass

class _PlainTidFormatter(logging.Formatter):

    def formatException(self, ei) -> str:
        return redact_text(super().formatException(ei))

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        tid = get_task_id()
        seg = f"[{tid}] " if tid else ""
        msg = redact_text(record.getMessage())
        if record.exc_info:
            msg = msg + "\n" + self.formatException(record.exc_info)
        return f"{ts} {record.levelname:<7} {record.name}  {seg}{msg}"

def _default_log_path() -> str:
    from engine.config.settings import DATA_DIR
    return os.path.join(str(DATA_DIR), "logs", "app.log")

def install_file_logging(
    path: str, max_bytes: int = 1_000_000, backup_count: int = 3
) -> _AppFileHandler | None:
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, _AppFileHandler):
            return h
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        handler = _AppFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
    except OSError:
        logging.getLogger("engine.config.logging_setup").debug(
            "file logging unavailable", exc_info=True
        )
        return None
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    handler.setFormatter(_PlainTidFormatter())
    root.addHandler(handler)
    return handler

_LOG_FICHIER_NON = ("0", "false", "no", "off")

def maybe_install_file_logging() -> _AppFileHandler | None:
    """Le journal sur disque est actif par defaut.

    L'anneau memoire de /api/logs ne garde que 400 lignes et meurt avec le
    processus : « pourquoi ce telechargement a echoue hier soir » n'avait aucune
    reponse. Quatre fichiers d'un Mo au plus, en 0600, dans data/logs/.

    ANIMESAMA_LOG_FILE : vide = emplacement par defaut, « 0 »/« false » = pas de
    fichier, toute autre valeur = chemin voulu.
    """
    brut = os.environ.get("ANIMESAMA_LOG_FILE", "").strip()
    if brut.lower() in _LOG_FICHIER_NON and brut:
        return None
    handler = install_file_logging(brut or _default_log_path())
    if handler is None:
        logging.getLogger("engine.config.logging_setup").warning(
            "Journal sur disque indisponible (dossier non inscriptible) — "
            "seules les 400 dernieres lignes resteront visibles dans le diagnostic."
        )
    return handler

def banner(title: str, *, url: str = "", subtitle: str = "") -> None:
    line = "─" * 50
    print(f"\n{C.CYAN}{line}{C.RESET}")
    print(f"  {C.BOLD}{title}{C.RESET}")
    if subtitle:
        print(f"  {C.DIM}{subtitle}{C.RESET}")
    if url:
        print(f"  {C.GREEN}→ {url}{C.RESET}")
    print(f"  {C.DIM}Ctrl+C pour arrêter{C.RESET}")
    print(f"{C.CYAN}{line}{C.RESET}\n")

def section(title: str) -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}▸ {title}{C.RESET}")

def step(text: str) -> None:
    print(f"  {C.BLUE}→{C.RESET} {text}")

def _fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"

def summary(
    *,
    title: str,
    succes: int = 0,
    echoues: int = 0,
    skipped: int = 0,
    duration: float = 0.0,
) -> None:
    line = "─" * 50
    print(f"\n{C.CYAN}{line}{C.RESET}")
    print(f"  {C.BOLD}Résumé : {title}{C.RESET}")
    if duration > 0:
        print(f"  {C.DIM}Durée : {_fmt_duration(duration)}{C.RESET}")
    if succes:
        print(f"  {C.GREEN}✓ Succès  : {succes}{C.RESET}")
    if skipped:
        print(f"  {C.YELLOW}⏭ Ignorés : {skipped}{C.RESET}")
    if echoues:
        print(f"  {C.RED}✗ Échecs  : {echoues}{C.RESET}")
    if not (succes or echoues or skipped):
        print(f"  {C.DIM}(aucun épisode traité){C.RESET}")
    print(f"{C.CYAN}{line}{C.RESET}\n")
