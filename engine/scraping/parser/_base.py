import ast
import importlib.util
import json
import logging
import re

from bs4 import BeautifulSoup, SoupStrainer, Tag

from engine.scraping.site.animessama import SITE_LANGS

log = logging.getLogger("engine.scraping.parser")

_STRAINER_A = SoupStrainer("a")
_STRAINER_EP_NAMES = SoupStrainer(["title", "select", "option"])
_STRAINER_TITREOEUVRE = SoupStrainer(attrs={"id": "titreOeuvre"})

HTML_MAX_SIZE = 5 * 1024 * 1024
MAX_JS_OBJECT_SCAN_SIZE = 500 * 1024
MAX_EPS_ARRAYS = 20

if importlib.util.find_spec("lxml") is not None:
    _BS_PARSER = "lxml"
    log.debug("Utilisation de lxml (rapide)")
else:  # pragma: no cover
    _BS_PARSER = "html.parser"
    log.warning("lxml non installé, fallback html.parser (plus lent)")

def _make_soup(html: str, parse_only: SoupStrainer | None = None) -> BeautifulSoup:
    if not html:
        return BeautifulSoup("", _BS_PARSER)
    if len(html) > HTML_MAX_SIZE:
        log.warning(
            f"_make_soup : HTML trop grand ({len(html) // 1024} Ko > "
            f"{HTML_MAX_SIZE // 1024} Ko) — tronqué"
        )
        html = html[:HTML_MAX_SIZE]
    if parse_only is not None:
        return BeautifulSoup(html, _BS_PARSER, parse_only=parse_only)
    return BeautifulSoup(html, _BS_PARSER)

def _attr_str(el: Tag, name: str, default: str = "") -> str:
    val = el.get(name, default)
    if isinstance(val, list):
        return " ".join(str(v) for v in val)
    return val if isinstance(val, str) else default

_RE_INVALID_FS = re.compile(r'[\\/:*?"<>|]')
_RE_LANG_SUFFIX = re.compile(r'\s+(?:VOSTFR|VF|VO)\s*$', re.I)
_RE_LANG_PAREN = re.compile(r'\s*\((?:VOSTFR|VF)\)\s*$', re.I)
_RE_EPS_ARRAY_HEAD = re.compile(r'var\s+(eps\d+)\s*=\s*(?=\[)')
_RE_SAISON_NUM = re.compile(r'saison(\d+)', re.I)
_LANG_ALT = "|".join(sorted(SITE_LANGS, key=len, reverse=True))
_RE_LANG_URL = re.compile(rf'/({_LANG_ALT})(?:/|$|\?)', re.I)
_RE_SLUG = re.compile(r'/catalogue/([^/?#]+)')

def _extraire_tableau_js(txt: str, start: int) -> str | None:
    bracket_start = txt.find("[", start)
    if bracket_start == -1:
        return None
    segment = txt[bracket_start:bracket_start + MAX_JS_OBJECT_SCAN_SIZE]
    depth = 0
    in_string = False
    escape_next = False
    str_char = ""
    for i, ch in enumerate(segment):
        if escape_next:
            escape_next = False
            continue
        if in_string:
            if ch == "\\":
                escape_next = True
            elif ch == str_char:
                in_string = False
            continue
        if ch in ('"', "'"):
            in_string = True
            str_char = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return segment[:i + 1]
    return None

_DROP_ARRAY = object()
_RE_JS_LINE_COMMENT = re.compile(r'(?m)^[ \t]*//[^\n]*$')

# Ce que le navigateur execute vraiment d'une fiche d'oeuvre. Le site y laisse
# trois sortes de code mort qui ressemblent a des panneaux (releve le 07/11/2026) :
# le commentaire de documentation commun (« panneauAnime("nom", ...) »), le gabarit
# « /*panneauScan("nom", "url")*/ » de chaque section, et des sections entieres
# desactivees par « <!-- MANGA ... --> » alors que leur appel est intact. Les
# commentaires JS se retirent script par script : un « /* » perdu dans une chaine
# (« image/* ») n'avale que son propre script. Un « <!-- » ouvert dans un script
# n'est pas un commentaire HTML, d'ou une seule alternance, gauche d'abord.
_RE_SCRIPT_OU_COMMENTAIRE_HTML = re.compile(
    r"(<script\b[^>]*>)(.*?)(</script\s*>)|<!--.*?-->", re.I | re.S
)
_RE_COMMENTAIRE_BLOC_JS = re.compile(r"/\*.*?\*/", re.S)


def _sans_code_mort(html: str) -> str:
    def _garder(m: re.Match) -> str:
        if m.group(1) is None:
            return " "
        js = _RE_COMMENTAIRE_BLOC_JS.sub(" ", m.group(2))
        return m.group(1) + _RE_JS_LINE_COMMENT.sub("", js) + m.group(3)

    return _RE_SCRIPT_OU_COMMENTAIRE_HTML.sub(_garder, html or "")


# Un vrai panneau n'est jamais le gabarit : ni le libelle « nom », ni le chemin « url ».
def _panneau_reel(libelle: str, chemin: str) -> bool:
    chemin = (chemin or "").strip().strip("/")
    return bool(chemin) and chemin.lower() != "url" and (libelle or "").strip().lower() != "nom"


_RE_URL_ID_VIDE = re.compile(r'[-=/]\.\w+([?#]|$)')
_RE_QUERY_ID_VIDE = re.compile(r'[?&](?:oid|id|videoid|video|watch)=(?:&|#|$)', re.I)

def _est_url_placeholder(url: str) -> bool:
    u = (url or "").strip()
    if not u or not u.startswith("http"):
        return True
    if u[-1] in "=/":
        return True
    if _RE_URL_ID_VIDE.search(u):
        return True
    return bool(_RE_QUERY_ID_VIDE.search(u))

def _parse_js_array(raw: str):
    try:
        urls = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = _RE_JS_LINE_COMMENT.sub("", raw)
        try:
            urls = ast.literal_eval(cleaned)
        except (ValueError, SyntaxError):
            return None
    return urls if isinstance(urls, list) else _DROP_ARRAY

def _extraire_eps_arrays(html: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    txt = html or ""
    for m in _RE_EPS_ARRAY_HEAD.finditer(txt):
        if len(result) >= MAX_EPS_ARRAYS:
            log.debug(
                f"_extraire_eps_arrays : plafond {MAX_EPS_ARRAYS} atteint — "
                "arrays supplémentaires ignorés"
            )
            break
        var_name = m.group(1)
        raw = _extraire_tableau_js(txt, m.end())
        if not raw:
            continue
        urls = _parse_js_array(raw)
        if urls is None:
            log.debug(f"_extraire_eps_arrays : impossible de parser {var_name}")
            continue
        if urls is _DROP_ARRAY:
            continue
        result[var_name] = ["" if not u else str(u) for u in urls]
    return result
