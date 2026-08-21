
import re

STREAM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'\.m3u8(\?|$)',               re.I),
    re.compile(r'master\.txt(\?|$)',          re.I),
    re.compile(r'index-v\d.*\.txt(\?|$)',     re.I),
    re.compile(r'/hls[2345]?/',               re.I),
    re.compile(r'/engine/hls',                re.I),
    re.compile(r'/secure/\d+/.*\.(m3u8|txt)', re.I),
]

_MP4_PATTERN: re.Pattern[str]  = re.compile(r'\.mp4(\?|$)',  re.I)
_MPD_PATTERN: re.Pattern[str]  = re.compile(r'\.mpd(\?|$)',  re.I)
_WEBM_PATTERN: re.Pattern[str] = re.compile(r'\.webm(\?|$)', re.I)

MEDIA_PATTERNS: list[re.Pattern[str]] = [_MP4_PATTERN, _MPD_PATTERN, _WEBM_PATTERN]

IGNORER: tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".css", ".js", ".ico", ".woff", ".woff2",
    "favicon", "analytics", "tracker", "doubleclick",
    "googlesyndication", "googletagmanager",
    "blank.mp4",
)

_JS_IGNORE_RE: re.Pattern[str] = re.compile(r'\.js($|[^o]|o[^n])')

def url_a_ignorer(url: str) -> bool:
    low = url.lower()
    path = low.split("?", 1)[0]
    for k in IGNORER:
        if k == ".js":
            if _JS_IGNORE_RE.search(path):
                return True
        elif k.startswith("."):
            if k in path:
                return True
        elif k in low:
            return True
    return False

def url_est_stream(url: str) -> bool:
    low = url.lower()
    if "m3u8" in low:
        return True
    if any(p.search(low) for p in STREAM_PATTERNS):
        return True
    return any(p.search(low) for p in MEDIA_PATTERNS)

def media_kind(url: str) -> str | None:
    low = url.lower()
    if "m3u8" in low or any(p.search(low) for p in STREAM_PATTERNS):
        return "hls"
    if _MPD_PATTERN.search(low):
        return "dash"
    if _MP4_PATTERN.search(low) or _WEBM_PATTERN.search(low):
        return "mp4"
    return None
