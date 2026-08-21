import logging
import re
from collections.abc import Callable
from typing import Any

from engine.config.settings import DEFAULT_USER_AGENT
from engine.download._engine_utils import safe_callback, safe_header
from engine.download.extractor.registry import get_extractor as _get_extractor

log = logging.getLogger("engine.download.methods.nm3u8dl")

RE_SEGMENTS = re.compile(r'(\d+)\s+Segments', re.I)

def get_thread_count(settings: dict[str, Any]) -> str:
    try:
        n = int(settings.get("thread_count", 16))
    except (TypeError, ValueError):
        n = 16
    n = max(1, min(32, n))
    return str(n)

def construire_commande(
    exe: str,
    url: str,
    dossier: str,
    nom: str,
    tmp_dir: str,
    headers: dict[str, str],
    settings: dict[str, Any],
    ffmpeg_path: str | None = None,
) -> list[str]:
    headers = headers or {}
    ext = _get_extractor(url)
    ua = safe_header(headers.get("user-agent") or DEFAULT_USER_AGENT) or DEFAULT_USER_AGENT
    referer = safe_header(headers.get("referer") or headers.get("origin", ""))
    referer = safe_header(ext.referer) or referer
    cookie = safe_header(headers.get("cookie", ""))
    origin = safe_header(ext.origin)
    threads = get_thread_count(settings)

    cmd = [
        exe, url,
        "--save-dir", dossier,
        "--save-name", nom,
        "--tmp-dir", tmp_dir,
        "--log-level", "INFO",
        "-M", "format=mp4",
        "--thread-count", threads,
        "--download-retry-count", "3",
        "--http-request-timeout", "30",
        "--check-segments-count", "false",
        "--no-date-info",
        "--disable-update-check",
        "--binary-merge",
        "--header", f"User-Agent: {ua}",
    ]

    if ffmpeg_path:
        cmd += ["--ffmpeg-binary-path", ffmpeg_path]

    qualite = str(settings.get("qualite", "auto")).strip()
    if qualite in ("1080", "720", "480"):
        cmd += ["-sv", f"res=x{qualite}:for=best", "-sa", "best"]
    else:
        cmd.append("--auto-select")

    if origin:
        cmd += ["--header", f"Origin: {origin}"]
    if referer:
        cmd += ["--header", f"Referer: {referer}"]
    if cookie:
        cmd += ["--header", f"Cookie: {cookie}"]

    return cmd

def interpreter_ligne(ligne: str, state: dict[str, Any], callback: Callable[[float, str], None] | None) -> None:
    m = RE_SEGMENTS.search(ligne)
    if m:
        try:
            state["total_segs"] = int(m.group(1))
        except (TypeError, ValueError):
            pass
        if state["phase"] != "downloading":
            log.info(f"Téléchargement de {state['total_segs']} segments...")
            state["phase"] = "downloading"

    if "Binary merging" in ligne or "Muxing" in ligne:
        if state["phase"] != "merging":
            log.info("Assemblage des segments...")
            state["phase"] = "merging"
        safe_callback(callback, 96.0, "🔧 Assemblage des segments…")
    elif "Cleaning" in ligne:
        safe_callback(callback, 98.0, "🧹 Nettoyage…")
    elif "Done" in ligne:
        state["phase"] = "done"
        safe_callback(callback, 100.0, "✅ Terminé !")
