import re
import threading

from engine.config.settings import DEFAULT_USER_AGENT
from engine.download._engine_utils import safe_header
from engine.download.extractor.registry import get_extractor as _get_extractor

_RE_OUT_TIME = re.compile(r'^out_time=(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)')
_RE_TOTAL_SIZE = re.compile(r'^total_size=(\d+)')
_RE_SPEED = re.compile(r'^speed=\s*([\d.]+)x')
_RE_BITRATE = re.compile(r'^bitrate=\s*([\d.]+)kbits/s')

def construire_commande(
    exe: str,
    url: str,
    sortie: str,
    headers: dict[str, str],
) -> list[str]:
    headers = headers or {}
    ext = _get_extractor(url)
    ua = safe_header(headers.get("user-agent") or DEFAULT_USER_AGENT)
    referer = safe_header(headers.get("referer") or headers.get("origin") or "")
    referer = safe_header(ext.referer) or referer
    cookie = safe_header(headers.get("cookie") or "")
    origin = safe_header(ext.origin)

    cmd = [
        exe,
        "-probesize", "5M",
        "-analyzeduration", "0",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-y",
        "-loglevel", "warning",
        "-stats",
        "-threads", "0",
        "-user_agent", ua,
    ]

    if referer:
        cmd += ["-referer", referer]
    entetes = []
    if origin:
        entetes.append(f"Origin: {origin}")
    if cookie:
        entetes.append(f"Cookie: {cookie}")
    if entetes:
        cmd += ["-headers", "".join(e + "\r\n" for e in entetes)]

    cmd += ["-protocol_whitelist", "crypto,http,https,tcp,tls"]

    cmd += ["-i", url]

    cmd += [
        "-fflags", "+genpts+igndts+discardcorrupt",
        "-err_detect", "ignore_err",
    ]

    cmd += [
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero",
    ]

    cmd += ["-progress", "pipe:1"]
    cmd.append(sortie)

    return cmd

class ProgressState:
    def __init__(self):
        self.lock = threading.Lock()
        self.out_time_s = 0.0
        self.total_size = 0
        self.speed = 0.0
        self.bitrate = 0.0
        self.done = False

def parse_progress_line(line: str, state: ProgressState) -> None:
    line = line.strip()
    with state.lock:
        m = _RE_OUT_TIME.match(line)
        if m:
            h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            state.out_time_s = h * 3600 + mn * 60 + s
            return
        m = _RE_TOTAL_SIZE.match(line)
        if m:
            state.total_size = int(m.group(1))
            return
        m = _RE_SPEED.match(line)
        if m:
            state.speed = float(m.group(1))
            return
        m = _RE_BITRATE.match(line)
        if m:
            state.bitrate = float(m.group(1))
            return
        if line == "progress=end":
            state.done = True

def construire_texte_progress(state: ProgressState, duree_totale_s: float) -> tuple[float, str]:
    with state.lock:
        t = state.out_time_s
        taille = state.total_size
        speed = state.speed
        bitrate = state.bitrate

    pct = 0.0
    if duree_totale_s > 0 and t > 0:
        pct = min(99.0, (t / duree_totale_s) * 100.0)

    h = int(t) // 3600
    mn = (int(t) % 3600) // 60
    sc = int(t) % 60
    t_str = f"{h:02d}:{mn:02d}:{sc:02d}"

    if taille > 0:
        if taille > 1_073_741_824:
            size_str = f"{taille/1_073_741_824:.1f} GB"
        elif taille > 1_048_576:
            size_str = f"{taille/1_048_576:.1f} MB"
        else:
            size_str = f"{taille/1024:.0f} KB"
    else:
        size_str = "?"

    speed_str = f"{speed:.1f}x" if speed > 0 else "?"
    bitrate_str = f"{bitrate:.0f} kb/s" if bitrate > 0 else ""

    if pct > 0:
        texte = f"{pct:.1f}% · {t_str} · {size_str}"
    else:
        texte = f"⏱ {t_str} · {size_str}"

    if bitrate_str:
        texte += f" · {bitrate_str}"
    if speed_str != "?":
        texte += f" · {speed_str}"

    return pct, texte
