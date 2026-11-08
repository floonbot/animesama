import logging
import os
import re
from urllib.parse import urlparse

from engine.config.settings import DEFAULT_USER_AGENT
from engine.download._engine_utils import borner_nom_fichier, safe_header
from engine.download.extractor.registry import get_extractor as _get_extractor

log = logging.getLogger("engine.download.methods.ytdlp_engine")

_RE_PROGRESS = re.compile(
    r'\[download\]\s+([\d.]+)%\s+of\s+~?([\d.]+\s*\w+)\s+at\s+([\d.]+\s*\w+/s)\s+ETA\s+([\d:]+|Unknown)'
)
_RE_PROGRESS_SIMPLE = re.compile(r'\[download\]\s+([\d.]+)%')

def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def _ytdlp_format_args(qualite: str) -> list[str]:
    q = (qualite or "auto").strip().lower().rstrip("p")
    if q in ("auto", ""):
        return ["--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"]
    if q == "1080":
        return ["--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"]
    if q == "720":
        return ["--format", "bestvideo[height<=720]+bestaudio/best[height<=720]"]
    if q == "480":
        return ["--format", "bestvideo[height<=480]+bestaudio/best[height<=480]"]
    return ["--format", "best"]

def construire_commande(
    exe: str,
    url: str,
    dossier: str,
    nom: str,
    headers: dict[str, str],
    qualite: str = "auto",
    aria2c: str | None = None,
    travail: str | None = None,
) -> list[str]:
    headers = headers or {}
    ua = safe_header(headers.get("user-agent") or DEFAULT_USER_AGENT)
    referer = safe_header(headers.get("referer") or headers.get("origin") or "")
    cookie = safe_header(headers.get("cookie") or "")
    nom = borner_nom_fichier(dossier, nom, ".mp4")
    if travail:
        # Telechargement et corrections dans `travail` (local), puis yt-dlp deplace
        # le resultat dans `dossier`. Sa correction HLS ajoute +faststart, qui
        # echoue sur un partage SMB. -P n'agit qu'avec un --output relatif.
        sortie = ["-P", f"home:{dossier}", "-P", f"temp:{travail}", "--output", nom + ".%(ext)s"]
    else:
        sortie = ["--output", os.path.join(dossier, nom + ".%(ext)s")]

    cmd = [
        exe,
        url,
        *sortie,
        "--merge-output-format", "mp4",
        "--no-part",
        # Jamais reprendre un fichier deja sur le disque : avec --no-part, un
        # telechargement coupe laisse la video finale tronquee, et yt-dlp la
        # reprendrait par une requete Range — depuis une *autre* source si on a
        # change de lecteur. Mesure : 140 ko du lecteur abandonne soudes a
        # 1,86 Mo du suivant, code retour 0, taille finale exacte.
        "--no-continue",
        "--windows-filenames",
        "--user-agent", ua,
        "--no-playlist",
        "--no-warnings",
        "--progress",
        "--newline",
        "--concurrent-fragments", "8",
        "--buffer-size", "16K",
        "--http-chunk-size", "10M",
        "--socket-timeout", "15",
        "--retries", "1",
        "--fragment-retries", "2",
        "--sleep-requests", "0.5",
        "--sleep-interval", "1",
        "--max-sleep-interval", "3",
        "--postprocessor-args",
        "ffmpeg:-fflags +genpts+igndts -avoid_negative_ts make_zero -movflags +faststart",
    ]

    if os.getenv("YTDLP_INSECURE", "").strip().lower() in ("1", "true", "yes"):
        cmd.append("--no-check-certificates")

    ext = _get_extractor(url)

    if aria2c and not ext.no_aria2c:
        cmd += [
            "--downloader", "aria2c",
            "--downloader-args", (
                "aria2c:"
                "-x 16 "
                "-s 16 "
                "-k 1M "
                "--file-allocation=none "
                "--retry-wait=2 "
                "--max-tries=2"
            ),
        ]

    cmd += _ytdlp_format_args(qualite)

    if ext.origin:
        cmd += ["--add-header", f"Origin:{ext.origin}"]
    ref = ext.referer or referer
    if ref:
        cmd += ["--referer", ref]

    if cookie:
        cmd += ["--add-header", f"Cookie:{cookie}"]

    if ext.extractor_args:
        cmd += ["--extractor-args", ext.extractor_args]

    # Le magasin du systeme a la place du certifi embarque. A ne pas confondre
    # avec YTDLP_INSECURE, qui lui ne verifie plus rien : ici on verifie autant,
    # contre un trousseau que Windows tient a jour.
    if ext.sans_certifi:
        cmd += ["--compat-options", "no-certifi"]

    return cmd

_RE_DEBIT = re.compile(r"([\d.]+)\s*([KMG]?i?B)/s", re.I)
_UNITES_DEBIT = {
    "b": 1.0,
    "kb": 1000.0, "mb": 1000.0 ** 2, "gb": 1000.0 ** 3,
    "kib": 1024.0, "mib": 1024.0 ** 2, "gib": 1024.0 ** 3,
}

def parser_debit(ligne: str) -> tuple[float, float] | None:
    """(pourcentage, octets/s) d'une ligne de progression chiffree, sinon None.

    yt-dlp ecrit « Unknown B/s » tant qu'il n'a pas de mesure : dans ce cas la
    ligne n'est pas exploitable et la regle d'abandon sur debit doit s'abstenir
    plutot que de lire un zero.
    """
    m = _RE_PROGRESS.search(ligne)
    if not m:
        return None
    d = _RE_DEBIT.search(m.group(3))
    if not d:
        return None
    facteur = _UNITES_DEBIT.get(d.group(2).lower())
    if facteur is None:
        return None
    try:
        return float(m.group(1)), float(d.group(1)) * facteur
    except ValueError:
        return None

def parser_progression(ligne: str) -> tuple[float, str] | None:
    m = _RE_PROGRESS.search(ligne)
    if m:
        pct = float(m.group(1))
        taille = m.group(2).strip()
        speed = m.group(3).strip()
        eta = m.group(4).strip()
        texte = f"{pct:.1f}% · {taille} · {speed} · ETA {eta}"
        return pct, texte
    m2 = _RE_PROGRESS_SIMPLE.search(ligne)
    if m2:
        pct = float(m2.group(1))
        return pct, f"{pct:.1f}%"
    return None
