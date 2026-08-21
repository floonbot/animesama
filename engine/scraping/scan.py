
import asyncio
import json
import logging
import re
import threading
import time
from urllib.parse import quote, urlencode

from engine.cache.disk_cache import DiskCache
from engine.observability.redact import redact_url
from engine.scraping.http_client import _get_session
from engine.scraping.site.animessama import (
    SCAN_API_CHAP,
    SCAN_LANGS,
    SITE_URL,
)

log = logging.getLogger("engine.scraping.scan")

_HTTP_TIMEOUT = 20
_BODY_DEADLINE = 60
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_HTML_BYTES = 4 * 1024 * 1024
_MAX_CHAPITRES = 5000
_MAX_PAGES = 10000

_RE_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9._-]{0,150}$", re.I)
# Un numero de chapitre, et rien d'autre : « 7 », « 12.5 ». Toute cle de la
# reponse etait prise pour un chapitre, y compris « error ».
_RE_CHAP_NUM = re.compile(r"^\d{1,5}(?:\.\d{1,3})?$")
_RE_TITRE = re.compile(
    r'<h3[^>]*id=["\']titreOeuvre["\'][^>]*>(.*?)</h3>', re.I | re.S
)
_RE_TAGS = re.compile(r"<[^>]+>")

_SCAN_INFO_TTL = 300.0
_scan_info_cache: dict[str, tuple[float, dict]] = {}
_scan_info_lock = threading.Lock()
_scan_disk = DiskCache("scan_info", 6 * 3600)

def _scan_info_get(key: str) -> dict | None:
    with _scan_info_lock:
        item = _scan_info_cache.get(key)
        if item and (time.time() - item[0]) < _SCAN_INFO_TTL:
            return item[1]
    return None

def _scan_info_set(key: str, value: dict) -> None:
    with _scan_info_lock:
        if len(_scan_info_cache) > 200:
            now = time.time()
            for k in [k for k, (ts, _) in _scan_info_cache.items() if now - ts >= _SCAN_INFO_TTL]:
                _scan_info_cache.pop(k, None)
            if len(_scan_info_cache) > 200:
                _scan_info_cache.clear()
        _scan_info_cache[key] = (time.time(), value)

def slug_valide(slug: str) -> bool:
    return bool(slug and isinstance(slug, str) and _RE_SLUG_OK.match(slug))

def normaliser_lang(lang: str | None) -> str:
    lang = (lang or "vf").strip().lower()
    return lang if lang in SCAN_LANGS else "vf"

def scan_page_url(slug: str, lang: str) -> str:
    return f"{SITE_URL}/catalogue/{slug}/scan/{lang}"

def _chap_sort_key(num: str) -> float:
    try:
        return float(num)
    except (TypeError, ValueError):
        return float("inf")

def _fetch_text(url: str, referer: str | None = None, max_bytes: int = _MAX_JSON_BYTES) -> tuple[int, str]:
    session = _get_session([])
    headers = {"Referer": referer} if referer else {}
    r = None
    try:
        r = session.get(url, headers=headers, timeout=_HTTP_TIMEOUT, stream=True)
        total = 0
        chunks: list[bytes] = []
        deadline = time.monotonic() + _BODY_DEADLINE
        for chunk in r.iter_content(64 * 1024):
            if time.monotonic() > deadline:
                log.warning("scan fetch %s : corps trop lent — tronqué", redact_url(url, 80))
                break
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                log.warning("scan fetch %s : réponse trop grande — tronquée", redact_url(url, 80))
                break
            chunks.append(chunk)
        encoding = r.encoding or "utf-8"
        try:
            text = b"".join(chunks).decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = b"".join(chunks).decode("utf-8", errors="replace")
        return r.status_code, text
    except Exception as e:
        log.debug("scan fetch %s : %s", redact_url(url, 80), e)
        return -1, ""
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass

def _extraire_oeuvre(html: str) -> str | None:
    m = _RE_TITRE.search(html or "")
    if not m:
        return None
    titre = _RE_TAGS.sub("", m.group(1))
    titre = titre.replace("&amp;", "&").strip()
    return titre or None

def _fetch_api_retry(url: str, referer: str | None = None, tries: int = 3) -> str | None:
    for i in range(tries):
        status, body = _fetch_text(url, referer=referer)
        if status == 200 and body.strip():
            return body
        if i < tries - 1:
            time.sleep(0.6)
    return None

def get_scan_info_sync(slug: str, lang: str = "vf") -> dict:
    if not slug_valide(slug):
        return {"ok": False, "error": "slug invalide", "chapitres": []}

    use = normaliser_lang(lang)
    cache_key = f"{slug}|{use}"
    cached = _scan_info_get(cache_key)
    if cached is not None:
        return cached
    disk_cached = _scan_disk.get(cache_key)
    if disk_cached is not None:
        _scan_info_set(cache_key, disk_cached)
        return disk_cached
    status, html = _fetch_text(scan_page_url(slug, use), max_bytes=_MAX_HTML_BYTES)
    if status != 200 or "selectChapitres" not in html:
        return {"ok": False, "error": "aucun scan pour cette œuvre", "chapitres": [], "langues": []}

    oeuvre = _extraire_oeuvre(html)
    if not oeuvre:
        return {"ok": False, "error": "titre d'œuvre introuvable", "chapitres": [], "langues": [use]}

    api = f"{SCAN_API_CHAP}?{urlencode({'oeuvre': oeuvre, 'lang': use})}"
    body = _fetch_api_retry(api, referer=scan_page_url(slug, use))
    if body is None:
        return {"ok": False, "error": "API chapitres injoignable", "chapitres": [],
                "langues": [use], "oeuvre": oeuvre, "lang": use}

    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return {"ok": False, "error": "réponse chapitres illisible", "chapitres": [],
                "langues": [use], "oeuvre": oeuvre, "lang": use}

    # Chaque cle de la reponse etait prise pour un numero de chapitre, sans
    # jamais verifier que c'en etait un. L'API repond
    # {"error":"Oeuvre 'X' not found"} pour les oeuvres qu'elle ne connait pas :
    # « error » devenait alors un chapitre, la fonction rendait ok=True avec
    # total=1, et la modale affichait « Commencer — Ch. error » avec une puce
    # « error ». Le garde-fou du front ne pouvait rien : ok etait vrai et la
    # liste n'etait pas vide.
    chapitres: list[dict] = []
    erreur_api = ""
    if isinstance(data, dict):
        for k, v in data.items():
            num = str(k).strip()
            # Une cle vide n'est un chapitre sous aucun angle — pas meme avec un
            # compte de pages credible, que la regle « ou pages > 0 » ci-dessous
            # laisserait autrement passer.
            if not num:
                continue
            try:
                pages = int(v)
            except (TypeError, ValueError):
                pages = 0
            # Deux facons d'etre un chapitre : porter un numero, ou annoncer un
            # nombre de pages. La premiere garde « 12.5 » meme si son compte est
            # illisible ; la seconde garde les chapitres speciaux nommes, qui
            # existent vraiment. « error », lui, n'a ni l'un ni l'autre : sa
            # valeur est une phrase.
            if not _RE_CHAP_NUM.match(num) and pages <= 0:
                if num.lower() == "error":
                    erreur_api = _RE_TAGS.sub("", str(v)).strip()[:200]
                continue
            chapitres.append({"num": num, "pages": pages})
            if len(chapitres) >= _MAX_CHAPITRES:
                break
    chapitres.sort(key=lambda c: _chap_sort_key(c["num"]))

    # Sans chapitre valide, il n'y a rien a lire ni a telecharger : le dire, et
    # ne pas mettre cet echec en cache — l'API peut apprendre l'oeuvre plus tard.
    #
    # Volontairement, on ne se rabat PAS sur le `creerListe(debut, fin)` que
    # certaines pages declarent en clair. Mesure du 17/08 sur Naruto : la page
    # annonce creerListe(1,700), l'API repond « not found », et les images
    # /s2/scans/Naruto/1/1.jpg rendent 404. Lire la page listerait 700 chapitres
    # tous injoignables — un mensonge plus couteux que l'aveu.
    if not chapitres:
        log.info("scan %s (%s) : aucun chapitre — %s", slug, use, erreur_api or "reponse vide")
        return {"ok": False, "error": erreur_api or "aucun chapitre pour cette œuvre",
                "chapitres": [], "langues": [use], "oeuvre": oeuvre, "lang": use}

    result = {
        "ok": True,
        "slug": slug,
        "oeuvre": oeuvre,
        "lang": use,
        "langues": [use],
        "chapitres": chapitres,
        "total": len(chapitres),
    }
    _scan_info_set(cache_key, result)
    _scan_disk.set(cache_key, result)
    return result

def get_pages_sync(oeuvre: str, chap: str, lang: str = "vf") -> list[dict]:
    oeuvre = (oeuvre or "").strip()
    chap = str(chap).strip()
    if not oeuvre or not chap:
        return []
    api = f"{SCAN_API_CHAP}?{urlencode({'oeuvre': oeuvre, 'lang': lang or 'vf'})}"
    body = _fetch_api_retry(api)
    if body is None:
        return []
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    try:
        nb = int(data.get(chap, 0))
    except (TypeError, ValueError):
        nb = 0
    if nb <= 0:
        return []
    nb = min(nb, _MAX_PAGES)
    base = f"{SITE_URL}/s2/scans/{quote(oeuvre, safe='')}/{quote(chap, safe='')}"
    return [{"page": i, "url": f"{base}/{i}.jpg"} for i in range(1, nb + 1)]

async def get_scan_info(slug: str, lang: str = "vf") -> dict:
    return await asyncio.to_thread(get_scan_info_sync, slug, lang)

async def get_pages(oeuvre: str, chap: str, lang: str = "vf") -> list[dict]:
    return await asyncio.to_thread(get_pages_sync, oeuvre, chap, lang)
