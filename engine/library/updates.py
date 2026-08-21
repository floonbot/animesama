import asyncio
import json
import logging
import re
import time
import unicodedata

from engine.cache.ttl_cache import TTLCache

log = logging.getLogger("engine.library.updates")

_UPDATES_CACHE_TTL = 300.0

_updates_tc = TTLCache(_UPDATES_CACHE_TTL, "updates")

def invalider_cache_updates() -> None:
    _updates_tc.invalidate()

def normaliser_nom(nom: str) -> str:
    if not nom:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(nom)[:500])
    n = nfkd.encode("ascii", "ignore").decode().lower().strip()
    n = re.sub(r"\s+(?:vostfr|vf|vo)\s*$", "", n)
    n = re.sub(r"\s+(?:saison|season|part|s)\s*\d+\s*$", "", n)
    n = re.sub(r"[^\w\s]", "", n)
    n = n.replace("_", "")
    n = re.sub(r"\s+", " ", n).strip()
    return n

def charger_exceptions_updates() -> dict:
    try:
        from engine.config.settings import DATA_DIR
        f = DATA_DIR / "ignore_updates.json"
        if not f.exists():
            return {}
        with open(f, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return {}
        exceptions: dict = {}
        for nom, regle in raw.items():
            if isinstance(regle, dict):
                exceptions[normaliser_nom(nom)] = regle
        return exceptions
    except Exception:
        log.debug("charger_exceptions_updates failed", exc_info=True)
        return {}

def _to_int_set(values) -> set[int]:
    out: set[int] = set()
    for v in values:
        try:
            out.add(int(v))
        except (TypeError, ValueError):
            continue
    return out

def ep_est_ignore(regle: dict, saison: int, episode: int) -> bool:
    if not regle:
        return False
    saisons_ign = regle.get("saisons_ignorees") or []
    try:
        if int(saison) in _to_int_set(saisons_ign):
            return True
    except (TypeError, ValueError):
        pass
    eps_ign = regle.get("episodes_ignores") or {}
    if isinstance(eps_ign, dict):
        liste = eps_ign.get(str(saison)) or []
        try:
            if int(episode) in _to_int_set(liste):
                return True
        except (TypeError, ValueError):
            pass
    return False

_RE_LANGUE_LOCALE = re.compile(
    r"\b(VOSTFR|VF1|VF2|VF|VAR|VKR|VCN|VQC|VA|VO)\s*$", re.I
)

def langue_locale(saisons: list[dict]) -> str:
    compteur: dict[str, int] = {}
    for saison in saisons or []:
        for ep in saison.get("episodes", []):
            m = _RE_LANGUE_LOCALE.search(ep.get("nom", ""))
            if m:
                lang = m.group(1).upper()
                compteur[lang] = compteur.get(lang, 0) + 1
    if not compteur:
        return ""
    return max(compteur, key=lambda k: compteur[k])

_RE_EP_NUM = re.compile(r"E(\d{1,4})", re.I)

def _norm_dossier(nom: str) -> str:
    return re.sub(r"\s+", " ", (nom or "").strip()).lower()

def episodes_locaux_par_dossier(saisons: list[dict]) -> dict[str, int]:
    par: dict[str, int] = {}
    for saison in saisons or []:
        folder = _norm_dossier(saison.get("nom", ""))
        if not folder:
            continue
        for ep in saison.get("episodes", []):
            nums = _RE_EP_NUM.findall(ep.get("nom", ""))
            if not nums:
                continue
            try:
                e = int(nums[-1])
            except (TypeError, ValueError):
                continue
            if e > par.get(folder, 0):
                par[folder] = e
    return par

def langue_locale_par_dossier(saisons: list[dict]) -> dict[str, str]:
    compteurs: dict[str, dict[str, int]] = {}
    for saison in saisons or []:
        folder = _norm_dossier(saison.get("nom", ""))
        if not folder:
            continue
        c = compteurs.setdefault(folder, {})
        for ep in saison.get("episodes", []):
            m = _RE_LANGUE_LOCALE.search(ep.get("nom", ""))
            if m:
                lang = m.group(1).upper()
                c[lang] = c.get(lang, 0) + 1
    return {folder: max(c, key=lambda k: c[k]) for folder, c in compteurs.items() if c}

async def check_updates_async(refresh: bool = False) -> dict:
    now = time.time()
    if not refresh:
        cached = _updates_tc.get()
        if cached is not None:
            return cached

    try:
        from engine.auth.manager import auth_manager
        from engine.library.scanner import scan_librairie_sync
        from engine.scraping.scraper import get_episodes_async, get_favorites_async

        if not auth_manager.is_logged_in:
            return {"animes": [], "total_nouveaux": 0, "checked_at": int(now), "non_connecte": True}

        librairie, favoris = await asyncio.gather(
            asyncio.to_thread(scan_librairie_sync),
            get_favorites_async(),
        )
        animes_locaux = librairie.get("animes", [])
        if not animes_locaux:
            result = {"animes": [], "total_nouveaux": 0, "checked_at": int(now)}
            _updates_tc.set(result)
            return result

        fav_par_nom: dict[str, dict] = {}
        for fav in favoris or []:
            cle = normaliser_nom(fav.get("nom", ""))
            if cle and cle not in fav_par_nom:
                fav_par_nom[cle] = fav

        a_verifier: list[tuple[dict, dict]] = []
        for a in animes_locaux:
            fav_match = fav_par_nom.get(normaliser_nom(a.get("nom", "")))
            if fav_match and fav_match.get("url"):
                a_verifier.append((a, fav_match))

        log.info("check-updates: %d/%d local animes matched a favorite", len(a_verifier), len(animes_locaux))

        if not a_verifier:
            result = {"animes": [], "total_nouveaux": 0, "checked_at": int(now)}
            _updates_tc.set(result)
            return result

        sem = asyncio.Semaphore(8)
        exceptions_updates = charger_exceptions_updates()
        nouveaux_par_anime: list[dict] = []
        non_verifies = 0

        async def _check_un_anime(anime_local: dict, fav: dict) -> dict | None:
            nonlocal non_verifies
            async with sem:
                try:
                    online = await asyncio.wait_for(get_episodes_async(fav["url"], force_refresh=refresh), timeout=90.0)
                except TimeoutError:
                    log.warning("check %s: timeout online (non vérifié)", anime_local["nom"])
                    non_verifies += 1
                    return None
                except Exception:
                    log.debug("check %s failed", anime_local["nom"], exc_info=True)
                    non_verifies += 1
                    return None

            online_eps = online.get("episodes") or []
            if not online_eps:
                # get_episodes_async rend une liste vide sur toutes ses sorties
                # d'echec : sans ce comptage, un scraping rate se presentait
                # comme « rien de neuf » et l'avertissement ne partait jamais.
                non_verifies += 1
                log.debug("check %s : aucun episode en ligne (non vérifié)", anime_local["nom"])
                return None

            from engine.scraping.parser import dossier_saison

            local_par_dossier = episodes_locaux_par_dossier(anime_local.get("saisons", []))
            local_langue = langue_locale(anime_local.get("saisons", []))
            langue_par_dossier = langue_locale_par_dossier(anime_local.get("saisons", []))
            regle_ignore = exceptions_updates.get(normaliser_nom(anime_local["nom"])) or {}
            nouveaux: list[dict] = []
            anime_titre = online.get("titre") or anime_local["nom"]

            for ep in online_eps:
                s_num = ep.get("saison") or 1
                e_num = ep.get("episode") or 0
                if e_num <= 0:
                    continue
                saison_nom = ep.get("saison_nom", "")
                saison_label = dossier_saison(saison_nom, s_num)
                dossier = _norm_dossier(saison_label)
                filtre_langue = langue_par_dossier.get(dossier) or local_langue
                if filtre_langue and (ep.get("langue", "") or "").upper() != filtre_langue:
                    continue
                if ep_est_ignore(regle_ignore, s_num, e_num):
                    continue
                max_local = local_par_dossier.get(dossier)
                if max_local is None:
                    nouveaux.append({
                        "url": ep.get("url", ""), "saison": s_num, "episode": e_num,
                        "titre": anime_titre, "langue": ep.get("langue", ""),
                        "saison_nom": saison_nom, "saison_label": saison_label,
                        "type": "nouvelle_saison",
                    })
                elif e_num > max_local:
                    nouveaux.append({
                        "url": ep.get("url", ""), "saison": s_num, "episode": e_num,
                        "titre": anime_titre, "langue": ep.get("langue", ""),
                        "saison_nom": saison_nom, "saison_label": saison_label,
                        "type": "nouveau",
                    })

            if not nouveaux:
                return None
            return {
                "nom": anime_local["nom"],
                "url": fav["url"],
                "image": fav.get("image", ""),
                "nouveaux_count": len(nouveaux),
                "nouveaux_episodes": nouveaux,
            }

        results = await asyncio.gather(
            *(_check_un_anime(a, fav) for a, fav in a_verifier),
            return_exceptions=True,
        )

        for r in results:
            if isinstance(r, dict):
                nouveaux_par_anime.append(r)
            elif isinstance(r, Exception):
                non_verifies += 1
        if non_verifies:
            log.warning("check-updates: %d anime(s) non vérifiés (timeout/erreur)", non_verifies)

        nouveaux_par_anime.sort(key=lambda x: x["nom"].lower())
        total = sum(a["nouveaux_count"] for a in nouveaux_par_anime)
        result = {"animes": nouveaux_par_anime, "total_nouveaux": total, "checked_at": int(now), "non_verifies": non_verifies}
        _updates_tc.set(result)
        log.info("check-updates: %d new episodes across %d animes", total, len(nouveaux_par_anime))
        return result

    except Exception:
        log.error("check_updates failed", exc_info=True)
        return {"animes": [], "total_nouveaux": 0, "checked_at": int(now), "erreur": True}
