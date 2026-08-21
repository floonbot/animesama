import re

_TOKEN_SEG = re.compile(r"[A-Za-z0-9]{24,}")
_B64URL_SEG = re.compile(r"[A-Za-z0-9_-]{32,}")
_URL_IN_TEXT = re.compile(r"https?://\S+")


def _has(seg: str, pred) -> bool:
    return any(pred(c) for c in seg)


def _looks_token(seg: str) -> bool:
    if _TOKEN_SEG.fullmatch(seg) and _has(seg, str.isdigit) and _has(seg, str.isalpha):
        return True
    return bool(
        _B64URL_SEG.fullmatch(seg)
        and _has(seg, str.isupper)
        and _has(seg, str.islower)
        and _has(seg, str.isdigit)
    )


def _caviar_path_tokens(base: str) -> str:
    parts = base.split("/")
    for i, seg in enumerate(parts):
        if _looks_token(seg):
            parts[i] = "…"
    return "/".join(parts)


def redact_url(url: object, limit: int = 120) -> str:
    """Return a log-safe form of *url*: query string and fragment dropped,
    userinfo credentials stripped, long opaque path token segments caviarded,
    length bounded.

    Strips everything from the first ``?`` or ``#`` (signed media URLs carry
    token/signature/expiry there) and any ``user:pass@`` authority prefix, then
    replaces path segments that look like an opaque access token with ``…`` —
    either alphanumeric (>= 24 chars, letters and digits) or URL-safe base64
    (>= 32 chars mixing upper, lower and digits, which distinguishes a
    high-entropy token from a lowercase-hyphen human slug). Human-readable slugs
    and short segments are kept for debugging. For URLs buried in free text
    (e.g. subprocess stderr) use ``redact_text``.
    """
    if not url:
        return ""
    base = str(url).split("#", 1)[0].split("?", 1)[0]
    base = re.sub(r"(://)[^/@]*@", r"\1", base, count=1)
    return _caviar_path_tokens(base)[:limit]


def redact_text(text: object) -> str:
    """Return *text* with every embedded ``http(s)://`` URL passed through
    ``redact_url`` — for log lines (e.g. subprocess stderr) that bury a signed
    URL inside arbitrary text.
    """
    if not text:
        return ""
    return _URL_IN_TEXT.sub(lambda m: redact_url(m.group(0), 300), str(text))
