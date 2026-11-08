import asyncio
import logging
import re
import time

from engine.cache.disk_cache import DiskCache
from engine.scraping._cache import cache
from engine.scraping.http_client import _is_safe_url, http_get
from engine.scraping.parser._base import _est_url_placeholder
from engine.scraping.players import _fetch_saison_arrays, url_episodes_js
from engine.scraping.site.animessama import SITE_LANGS, SITE_URL

log = logging.getLogger("engine.scraping.episodes")

# Les entrees portent les noms de saisons de parse_panneaux, et le telechargement
# range les fichiers d'apres ces noms. Le cache survit une heure au redemarrage :
# changer cette version a chaque fois que le parseur rend autre chose pour une
# meme page, sinon la mise a jour resservirait les noms de l'ancien binaire.
# 2 — commentaire de documentation de la fiche ignore (11/2026).
# 3 — sections desactivees par <!-- ... --> ignorees (07/11/2026).
_VERSION_CACHE = "3"

_ep_disk = DiskCache("episodes", 3600, version=_VERSION_CACHE)


def invalidate_ep_disk(url: str | None = None) -> None:
    if url is None:
        _ep_disk.clear()
        return
    cache_key = url.split("?")[0].rstrip("/")
    keys = [cache_key]
    m = re.search(r"/catalogue/([^/?#]+)", url)
    if m:
        keys.append(f"{SITE_URL}/catalogue/{m.group(1)}")
    _ep_disk.delete(*keys)

_LANG_ALT = "|".join(sorted(SITE_LANGS, key=len, reverse=True))
_RE_LANG = re.compile(rf"/({_LANG_ALT})(?:/|$|\?|#)", re.I)

def _episodes_js_url(saison_url: str, html: str = "") -> str:
    return url_episodes_js(saison_url, html)

def _norm_saison_url(u: str | None) -> str:
    return (u or "").split("?")[0].rstrip("/").lower()

async def _fetch_saison_parsed(saison_url: str, cookies) -> dict:
    from engine.scraping.parser import parse_episodes
    r = await http_get(saison_url, cookies)
    if not r:
        return {}
    parsed = await asyncio.to_thread(parse_episodes, r.text, saison_url)
    if parsed.get("episodes"):
        return parsed
    r2 = await http_get(_episodes_js_url(saison_url, r.text), cookies)
    if r2 and getattr(r2, "text", ""):
        combined = f"{r.text}\n<script>{r2.text}</script>"
        parsed2 = await asyncio.to_thread(parse_episodes, combined, saison_url)
        if parsed2.get("episodes"):
            return parsed2
    return parsed

async def _fetch_saison(saison_url: str, cookies) -> dict:
    return await _fetch_saison_parsed(saison_url, cookies)

_LANGS_EPISODES = ("vostfr", "vf")
_PANNEAUX_MAX = 40
_RE_H1_TITRE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_RE_TAGS = re.compile(r"<[^>]+>")
_RE_SEG_SAISON_SIMPLE = re.compile(r"^saison\d+$", re.I)

def _episodes_reels(arrays: dict[str, list[str]]) -> list[int]:
    if not arrays:
        return []
    n = max((len(v) for v in arrays.values()), default=0)
    out: list[int] = []
    for i in range(n):
        if any(i < len(v) and not _est_url_placeholder(v[i]) for v in arrays.values()):
            out.append(i + 1)
    return out

def _construire_episodes(slug: str, titre: str, infos: list[tuple]) -> list[dict]:
    par_langue: dict[str, list[tuple]] = {}
    for idx, nom, seg, lang, eps_nums in infos:
        par_langue.setdefault(lang, []).append((idx, nom, seg, eps_nums))

    episodes: list[dict] = []
    for lang, panels in par_langue.items():
        panels.sort(key=lambda p: p[0])
        tout_saison_simple = all(_RE_SEG_SAISON_SIMPLE.match(seg) for _, _, seg, _ in panels)
        fusion = len(panels) >= 2 and tout_saison_simple and all(len(en) == 1 for _, _, _, en in panels)

        if fusion:
            for ep_affiche, (_idx, _nom, seg, eps_nums) in enumerate(panels, 1):
                episodes.append({
                    "url": f"{SITE_URL}/catalogue/{slug}/{seg}/{lang}?ep={eps_nums[0]}",
                    "saison": 1,
                    "episode": ep_affiche,
                    "titre": titre,
                    "langue": lang.upper(),
                    "saison_nom": "Saison 1",
                })
        else:
            for idx, nom, seg, eps_nums in panels:
                base = f"{SITE_URL}/catalogue/{slug}/{seg}/{lang}"
                for src in eps_nums:
                    episodes.append({
                        "url": f"{base}?ep={src}",
                        "saison": idx,
                        "episode": src,
                        "titre": titre,
                        "langue": lang.upper(),
                        "saison_nom": nom,
                    })
    return episodes

def _titre_fiche(html: str) -> str:
    m = _RE_H1_TITRE.search(html or "")
    if m:
        titre = _RE_TAGS.sub("", m.group(1)).replace("&amp;", "&").strip()
        if titre:
            return titre[:200]
    m2 = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    if m2:
        titre = _RE_TAGS.sub("", m2.group(1)).replace("Anime-Sama - ", "").strip()
        return titre[:200] if titre else ""
    return ""

async def _episodes_depuis_panneaux(
    slug: str, fiche_html: str, panneaux: list[dict], cookies,
) -> tuple[dict, bool]:
    titre = _titre_fiche(fiche_html)
    plans = [
        (idx, pan["nom"], pan["seg"], lang)
        for idx, pan in enumerate(panneaux[:_PANNEAUX_MAX], 1)
        for lang in _LANGS_EPISODES
    ]
    infos: list = [None] * len(plans)
    sem = asyncio.Semaphore(4)

    async def _un(k: int, idx: int, nom: str, seg: str, lang: str):
        url = f"{SITE_URL}/catalogue/{slug}/{seg}/{lang}"
        async with sem:
            arrays, ok = await _fetch_saison_arrays(url, cookies)
        if not ok or not arrays:
            return
        eps_nums = _episodes_reels(arrays)
        if not eps_nums:
            return
        infos[k] = (idx, nom, seg, lang, eps_nums[:2000])

    complet = True
    try:
        await asyncio.wait_for(
            asyncio.gather(*[_un(k, *p) for k, p in enumerate(plans)]),
            timeout=60.0,
        )
    except TimeoutError:
        complet = False
        log.warning("get_episodes (panneaux) : timeout 60s — résultat partiel")

    episodes = _construire_episodes(slug, titre, [x for x in infos if x])
    episodes.sort(key=lambda e: (e["saison"], e["langue"], e["episode"]))
    langues = sorted({e["langue"] for e in episodes})
    result = {"titre": titre, "episodes": episodes, "langues": langues, "total": len(episodes)}
    return result, complet

def _detecter_langue(anime_url: str) -> str:
    m = _RE_LANG.search(anime_url or "")
    return m.group(1).lower() if m else "vostfr"

async def _lister_saisons_par_sondage(
    cookies,
    slug: str,
    lang: str,
    saison_max_connu: int = 1,
) -> list[dict]:
    saisons: list[dict] = []
    vides_consecutifs = 0
    n = 1
    deadline = time.time() + 45
    while n <= 20 and time.time() < deadline:
        url = f"{SITE_URL}/catalogue/{slug}/saison{n}/{lang}"
        parsed = await _fetch_saison_parsed(url, cookies)
        eps = parsed.get("episodes") or []
        if eps:
            saisons.append({"saison": n, "url": url, "lang": lang, "_parsed": parsed})
            vides_consecutifs = 0
        else:
            vides_consecutifs += 1
            if n >= saison_max_connu and vides_consecutifs >= 2:
                break
            if vides_consecutifs >= 3:
                break
        n += 1

    log.debug(f"_lister_saisons_par_sondage({slug}, {lang}) → {len(saisons)} saison(s)")
    return saisons

async def get_episodes_async(anime_url: str, force_refresh: bool = False) -> dict:
    from engine.auth.manager import auth_manager
    from engine.scraping.parser import parse_panneaux, parse_saisons

    empty = {"titre": "", "episodes": [], "langues": [], "total": 0}

    if not _is_safe_url(anime_url):
        log.warning(f"URL refusée : {(anime_url or '')[:60]}")
        return empty

    if anime_url.startswith("/"):
        anime_url = SITE_URL + anime_url

    cache_key = anime_url.split("?")[0].rstrip("/")

    if not force_refresh:
        cached = cache.get_ep(cache_key)
        if cached is not None:
            log.debug(f"Épisodes depuis cache : {cache_key[:60]}")
            return cached

    lock = cache.ep_lock(cache_key)
    if lock is None:
        log.error("get_episodes_async : impossible d'obtenir le lock asyncio")
        return empty

    async with lock:
        if not force_refresh:
            cached = cache.get_ep(cache_key)
            if cached is not None:
                return cached
            disk_cached = await asyncio.to_thread(_ep_disk.get, cache_key)
            if disk_cached is not None:
                cache.set_ep(cache_key, disk_cached)
                log.debug(f"Épisodes depuis cache disque : {cache_key[:60]}")
                return disk_cached

        try:
            m_slug_url = re.search(r"/catalogue/([^/?#]+)", anime_url)
            if m_slug_url:
                fiche_url = f"{SITE_URL}/catalogue/{m_slug_url.group(1)}"
            else:
                fiche_url = anime_url

            fiche_cache_key = fiche_url.rstrip("/")

            if fiche_cache_key != cache_key and not force_refresh:
                cached_fiche = cache.get_ep(fiche_cache_key)
                if cached_fiche is not None:
                    log.debug(f"Épisodes depuis cache (fiche) : {fiche_cache_key[:60]}")
                    return cached_fiche
                disk_fiche = await asyncio.to_thread(_ep_disk.get, fiche_cache_key)
                if disk_fiche is not None:
                    cache.set_ep(fiche_cache_key, disk_fiche)
                    return disk_fiche

            r_fiche = await http_get(fiche_url, auth_manager.cookies)
            if not r_fiche:
                return empty

            panneaux = await asyncio.to_thread(parse_panneaux, r_fiche.text)
            if panneaux and m_slug_url:
                result, complet = await _episodes_depuis_panneaux(
                    m_slug_url.group(1), r_fiche.text, panneaux, auth_manager.cookies
                )
                if result.get("episodes"):
                    if complet:
                        cache.set_ep(fiche_cache_key, result)
                        if fiche_cache_key != cache_key:
                            cache.set_ep(cache_key, result)
                        _disk_keys = {cache_key: result}
                        if fiche_cache_key != cache_key:
                            _disk_keys[fiche_cache_key] = result
                        await asyncio.to_thread(_ep_disk.set_many, _disk_keys)
                    return result

            saisons = await asyncio.to_thread(parse_saisons, r_fiche.text)

            distinct_saisons = {s.get("saison") for s in saisons}
            if len(distinct_saisons) <= 1 and m_slug_url:
                slug = m_slug_url.group(1)
                lang = _detecter_langue(anime_url)
                saison_max = max((s.get("saison", 1) for s in saisons), default=1)
                saisons_sondees = await _lister_saisons_par_sondage(
                    auth_manager.cookies, slug, lang, saison_max_connu=saison_max
                )
                if saisons_sondees:
                    log.info(
                        f"get_episodes_async : fiche ne liste que "
                        f"{len(distinct_saisons)} saison(s) → sondage trouve "
                        f"{len(saisons_sondees)} saison(s) pour {slug}"
                    )
                    urls_connues = {_norm_saison_url(s.get("url")) for s in saisons}
                    saisons = saisons + [
                        s for s in saisons_sondees
                        if _norm_saison_url(s.get("url")) not in urls_connues
                    ]

            if not saisons:
                log.warning(f"Aucune saison trouvée sur la fiche : {fiche_url[:60]}")
                if re.search(r"/saison\d+/", anime_url, re.I):
                    result = await _fetch_saison(cache_key, auth_manager.cookies)
                    if result.get("episodes"):
                        cache.set_ep(cache_key, result)
                    return result or empty
                return empty

            if len(saisons) > 20:
                log.warning(f"get_episodes_async : {len(saisons)} saisons — tronqué à 20")
                saisons = saisons[:20]

            tous_episodes: list[dict] = []
            titre = ""
            langues: set[str] = set()

            async def _fetch_toutes_saisons():
                nonlocal titre
                sem = asyncio.Semaphore(6)
                parts: list = [None] * len(saisons)

                async def _une(idx, s):
                    ep_data = s.get("_parsed")
                    if ep_data is None:
                        async with sem:
                            ep_data = await _fetch_saison_parsed(s["url"], auth_manager.cookies)
                    if ep_data:
                        parts[idx] = ep_data

                try:
                    await asyncio.gather(*[_une(i, s) for i, s in enumerate(saisons)])
                finally:
                    for ep_data in parts:
                        if ep_data is None:
                            continue
                        if not titre:
                            titre = ep_data.get("titre", "")
                        tous_episodes.extend(ep_data.get("episodes", []))
                        langues.update(ep_data.get("langues", []))

            complet = True
            try:
                await asyncio.wait_for(_fetch_toutes_saisons(), timeout=60.0)
            except TimeoutError:
                complet = False
                log.warning(
                    f"get_episodes_async : timeout 60s — {len(tous_episodes)} "
                    f"épisodes récupérés (partiel, non mis en cache)"
                )
                if not tous_episodes:
                    return empty

            if not tous_episodes:
                return empty

            result = {
                "titre": titre,
                "episodes": tous_episodes,
                "langues": sorted(langues),
                "total": len(tous_episodes),
            }
            if complet:
                cache.set_ep(fiche_cache_key, result)
                if fiche_cache_key != cache_key:
                    cache.set_ep(cache_key, result)
                _disk_keys = {cache_key: result}
                if fiche_cache_key != cache_key:
                    _disk_keys[fiche_cache_key] = result
                await asyncio.to_thread(_ep_disk.set_many, _disk_keys)
            return result

        except Exception as e:
            log.error(f"get_episodes_async : {e}", exc_info=True)
            return empty
