"""Veille des nouveaux episodes, en arriere-plan.

Refait periodiquement ce que fait le bouton « Nouveautes » de la librairie, et
ne signale que ce qui n'a pas deja ete signale : un episode encore en attente
n'est pas renotifie toutes les six heures. Avec ``veille_auto_dl``, les episodes
nouvellement apparus des oeuvres de la watchlist partent seuls en file — une
seule fois : un echec de telechargement reste visible dans « Nouveautes »
plutot que d'etre relance en boucle.
"""

import asyncio
import json
import logging
import os
import sys
import time

from engine.config.settings import DATA_DIR

log = logging.getLogger("engine.library.veille")

INTERVALLES_H = (1, 3, 6, 12, 24)
INTERVALLE_DEFAUT_H = 6
_DELAI_DEMARRAGE_S = 120  # laisser l'app demarrer avant ~500 requetes au site
_PAS_S = 60
_ETAT_FICHIER = DATA_DIR / "veille_nouveautes.json"


def _charger_etat() -> dict:
    try:
        with open(_ETAT_FICHIER, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {"derniere": float(data.get("derniere") or 0),
                    "signales": [u for u in data.get("signales") or [] if isinstance(u, str)]}
    except (OSError, ValueError, TypeError):
        pass
    return {"derniere": 0.0, "signales": []}


def _sauver_etat(etat: dict) -> None:
    try:
        _ETAT_FICHIER.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ETAT_FICHIER.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(etat, f)
        os.replace(tmp, _ETAT_FICHIER)
    except OSError as e:
        log.debug(f"veille : état non sauvé ({e})")


def intervalle_h(reglages: dict) -> int:
    try:
        h = int(reglages.get("veille_intervalle_h", INTERVALLE_DEFAUT_H))
    except (TypeError, ValueError):
        return INTERVALLE_DEFAUT_H
    return h if h in INTERVALLES_H else INTERVALLE_DEFAUT_H


def _resume(animes: list[tuple[dict, list[dict]]]) -> str:
    morceaux = [f"{a['nom']} ({len(eps)})" for a, eps in animes[:4]]
    if len(animes) > 4:
        morceaux.append(f"+{len(animes) - 4} autre{'s' if len(animes) > 5 else ''}")
    return ", ".join(morceaux)


async def un_tour() -> dict | None:
    """Une verification ; None si rien n'a ete tente (veille coupee, pas de session).

    Un echec du site rend {"echec": True} : l'appelant doit alors attendre comme
    apres un succes, sinon il relancerait quelque 500 requetes chaque minute.
    """
    from engine.auth.manager import auth_manager
    from engine.config.user_settings import load_settings
    from engine.library.updates import check_updates_async

    reglages = load_settings()
    if not reglages.get("veille_nouveautes", True) or not auth_manager.is_logged_in:
        return None

    resultat = await check_updates_async(refresh=True)
    if resultat.get("non_connecte"):
        return None
    if resultat.get("erreur"):
        return {"echec": True}

    etat = await asyncio.to_thread(_charger_etat)
    deja = set(etat["signales"])
    frais: list[tuple[dict, list[dict]]] = []
    for a in resultat.get("animes") or []:
        eps = [e for e in a.get("nouveaux_episodes") or [] if e.get("url") not in deja]
        if eps:
            frais.append((a, eps))

    en_file = 0
    if frais and reglages.get("veille_auto_dl", False):
        from engine.services.download_service import download_service

        for a, eps in frais:
            if "watchlist" not in (a.get("listes") or []):
                continue
            try:
                await download_service.ajouter_episode({"ep": dict(eps[0]), "episodes": [dict(e) for e in eps]})
                en_file += len(eps)
            except Exception:
                log.warning("veille : mise en file de %s impossible", a.get("nom"), exc_info=True)

    # Seuls les episodes encore en attente restent retenus : la liste ne grossit pas.
    etat["signales"] = [e.get("url") for a in resultat.get("animes") or []
                        for e in a.get("nouveaux_episodes") or [] if e.get("url")]
    etat["derniere"] = time.time()
    await asyncio.to_thread(_sauver_etat, etat)

    bilan = {
        "total": sum(len(eps) for _, eps in frais),
        "animes": [{"nom": a["nom"], "nouveaux": len(eps)} for a, eps in frais],
        "en_file": en_file,
        "total_en_attente": resultat.get("total_nouveaux", 0),
    }
    _annoncer(bilan, frais)
    log.info("veille : %d nouvel(s) épisode(s) signalé(s), %d mis en file", bilan["total"], en_file)
    return bilan


def _annoncer(bilan: dict, frais: list[tuple[dict, list[dict]]]) -> None:
    # Toujours emis : la pastille de l'onglet Librairie suit total_en_attente,
    # meme quand rien de neuf n'est apparu depuis le tour precedent.
    try:
        from web.api.routes.sse import emit
        emit("nouveautes", bilan)
    except Exception:
        log.debug("veille : événement SSE non émis", exc_info=True)
    if not frais:
        return
    n = bilan["total"]
    titre = f"🆕 {n} nouvel{'s' if n > 1 else ''} épisode{'s' if n > 1 else ''}"
    corps = _resume(frais)
    if bilan["en_file"]:
        corps += f" — {bilan['en_file']} ajouté{'s' if bilan['en_file'] > 1 else ''} au téléchargement"
    try:
        from engine.utils.notifications import notifier
        notifier(titre, corps)
    except Exception:
        log.debug("veille : notification non émise", exc_info=True)


async def boucle() -> None:
    from engine.config.user_settings import load_settings

    await asyncio.sleep(_DELAI_DEMARRAGE_S)
    tentative = 0.0  # en memoire : un echec n'ecrit pas « derniere »
    while True:
        try:
            reglages = await asyncio.to_thread(load_settings)
            if reglages.get("veille_nouveautes", True):
                derniere = (await asyncio.to_thread(_charger_etat))["derniere"]
                if time.time() - max(derniere, tentative) >= intervalle_h(reglages) * 3600:
                    if await un_tour() is not None:
                        tentative = time.time()
        except asyncio.CancelledError:
            raise
        except Exception:
            tentative = time.time()
            log.warning("veille : tour en échec", exc_info=True)
        await asyncio.sleep(_PAS_S)


def demarrer() -> asyncio.Task | None:
    # Comme la mise a jour de yt-dlp : jamais sous pytest, ou chaque TestClient
    # lancerait des centaines de requetes au site.
    if "pytest" in sys.modules:
        return None
    return asyncio.create_task(boucle(), name="veille-nouveautes")
