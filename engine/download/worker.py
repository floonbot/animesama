
import asyncio
import logging
import os
import time
import uuid
from typing import Any

from engine.config.settings import get_downloads_dir, get_scans_dir
from engine.domain.exceptions import DownloadCancelled
from engine.download._helpers import normaliser_episodes as _normaliser_episodes
from engine.download._runtime import (
    HISTORIQUE_MAX,
    _est_annule,
    _historique_ajouter,
    _historique_append,
    _run_in_pool,
    _safe_emit,
    _signaler_annulation_engine,
    shutdown,
)
from engine.download.pipeline import _PREFETCH_ENABLED, _traiter_un_episode, prefetch_extraction
from engine.observability.context import task_context
from engine.scraping.parser import nettoyer_titre

log = logging.getLogger("engine.download.worker")

__all__ = [
    "HISTORIQUE_MAX",
    "_est_annule",
    "_historique_ajouter",
    "_historique_append",
    "shutdown",
    "traiter_item",
]

MAX_EPISODE_DURATION = 3 * 3600 + 1800
DELAI_MIN_EPISODES = 3.0
_EPISODE_POLL_S = 0.5


async def _attendre_avec_budget(coro: Any, queue: Any) -> Any:
    paused = getattr(queue, "_paused", None)
    task = asyncio.ensure_future(coro)
    reste = float(MAX_EPISODE_DURATION)
    try:
        while True:
            en_pause = bool(paused is not None and paused.is_set())
            tranche = _EPISODE_POLL_S if en_pause else min(_EPISODE_POLL_S, reste)
            done, _ = await asyncio.wait({task}, timeout=tranche)
            if done:
                return task.result()
            if not en_pause:
                reste -= tranche
                if reste <= 0:
                    raise TimeoutError
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

async def _pause_anti_ban(queue) -> None:
    from engine.download._rate_limiter import cooldown_global
    pause = DELAI_MIN_EPISODES + cooldown_global()
    if pause <= DELAI_MIN_EPISODES + 0.01:
        await asyncio.sleep(DELAI_MIN_EPISODES)
        return
    log.warning("Anti-ban : throttling récent → pause %ds avant l'épisode suivant", int(pause))
    _safe_emit(queue, "episode_progress", {
        "pct": 0, "line": f"Anti-ban : pause {int(pause)}s pour éviter le blocage…",
    })
    reste = pause
    while reste > 0 and not _est_annule(queue):
        await asyncio.sleep(min(1.0, reste))
        reste -= 1.0

async def _attendre_reprise(queue) -> None:
    paused = getattr(queue, "_paused", None)
    if paused is None:
        return
    while paused.is_set() and not _est_annule(queue):
        await asyncio.sleep(0.5)

async def traiter_item(item: dict[str, Any], queue) -> None:
    if not isinstance(item, dict):
        log.error("invalid queue item (not a dict)")
        return
    raw_id = item.get("id")
    tid = raw_id if isinstance(raw_id, str) and raw_id else ""
    if item.get("_scan"):
        with task_context(tid or uuid.uuid4().hex[:6]):
            await _traiter_scan(item, queue)
    elif item.get("_direct"):
        with task_context(tid or uuid.uuid4().hex[:6]):
            await _traiter_direct(item, queue)
    elif tid:
        with task_context(tid):
            await _traiter_episode(item, queue)
    else:
        await _traiter_episode(item, queue)

async def _traiter_direct(item: dict[str, Any], queue) -> None:
    from engine.download.methods.nm3u8dl import nm3u8dl_download

    nom_dl = item.get("nom") or "Episode"
    url = item.get("url_stream", "")
    hdrs = item.get("headers_stream") or {}
    dossier = str(get_downloads_dir() / "Direct")

    if not url:
        log.error("direct download refused: missing URL (%s)", nom_dl)
        _historique_ajouter(queue, nom_dl, "", succes=0, echoues=1)
        _safe_emit(queue, "episode_done", {"nom": nom_dl, "succes": False, "erreur": "URL manquante"})
        _safe_emit(queue, "queue_updated", queue.statut())
        return

    from engine.download.pipeline import _motif_url_refusee

    motif = await asyncio.to_thread(_motif_url_refusee, url)
    if motif:
        log.error("téléchargement direct refusé (%s) — %s", nom_dl, motif)
        _historique_ajouter(queue, nom_dl, "", succes=0, echoues=1)
        _safe_emit(queue, "episode_done", {"nom": nom_dl, "succes": False, "erreur": motif[:400]})
        _safe_emit(queue, "queue_updated", queue.statut())
        return

    log.info("direct download: %s", nom_dl)
    _safe_emit(queue, "episode_start", {"nom": nom_dl, "index": 0, "total": 1})

    def on_progress(pct, ligne):
        _safe_emit(queue, "episode_progress", {"pct": pct, "line": ligne})

    fichier: str | None = None
    annule = False
    erreur_msg = ""
    try:
        cancelled = getattr(queue, "_cancelled", None)
        fichier = await _attendre_avec_budget(
            _run_in_pool(nm3u8dl_download, url, dossier, nom_dl, hdrs, cancelled, on_progress),
            queue,
        )
    except TimeoutError:
        await _signaler_annulation_engine(queue)
        erreur_msg = f"timeout global ({MAX_EPISODE_DURATION}s)"
        log.error("direct download timeout (%s)", nom_dl)
    except DownloadCancelled:
        annule = True
        log.info("download cancelled: %s", nom_dl)
    except RuntimeError as exc:
        erreur_msg = str(exc)[:200]
        log.error("download failed (%s): %s", nom_dl, erreur_msg)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        erreur_msg = str(exc)[:200]
        log.error("download failed (%s): %s", nom_dl, erreur_msg)

    ok = bool(fichier and os.path.exists(fichier))
    if not ok and not annule and not erreur_msg:
        erreur_msg = (
            "Le flux n'a pas pu être téléchargé — lien expiré, hôte injoignable "
            "ou composant de téléchargement manquant (voir le diagnostic)"
        )
    if annule:
        _safe_emit(queue, "dl_annule", {"nom": nom_dl})
    _safe_emit(queue, "episode_done", {
        "nom": nom_dl, "succes": ok, "skipped": False, "annule": annule, "erreur": erreur_msg,
    })
    _historique_ajouter(queue, nom_dl, "", succes=int(ok), echoues=int(not ok and not annule))
    _safe_emit(queue, "queue_updated", queue.statut())

async def _traiter_scan(item: dict[str, Any], queue) -> None:
    from engine.download.methods.images import scan_download

    nom = item.get("nom") or item.get("oeuvre") or "Scan"
    oeuvre = item.get("oeuvre", "")
    lang = (item.get("lang") or "vf").lower()
    chapitres = [str(c) for c in (item.get("chapitres") or []) if str(c).strip()]
    dossier = str(get_scans_dir() / nettoyer_titre(nom) / f"Scan {lang.upper()}")
    total = len(chapitres)

    if not oeuvre or not chapitres:
        log.error("scan refused: missing oeuvre/chapitres (%s)", nom)
        _safe_emit(queue, "episode_done", {"nom": nom, "succes": False, "erreur": "Scan invalide"})
        _historique_ajouter(queue, nom, lang.upper(), echoues=1)
        _safe_emit(queue, "queue_updated", queue.statut())
        return

    log.info("scan download: %s (%s) — %d chapitre(s)", nom, lang, total)
    _safe_emit(queue, "episode_start", {"nom": nom, "index": 0, "total": total})

    def on_progress(pct, ligne):
        _safe_emit(queue, "episode_progress", {"pct": pct, "line": ligne})

    fichier: str | None = None
    annule = False
    erreur_msg = ""
    try:
        cancelled = getattr(queue, "_cancelled", None)
        fichier = await _run_in_pool(
            scan_download, oeuvre, lang, chapitres, dossier, cancelled, on_progress
        )
    except DownloadCancelled:
        annule = True
        log.info("scan cancelled: %s", nom)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        erreur_msg = str(exc)[:200]
        log.error("scan download failed (%s): %s", nom, erreur_msg)

    ok = bool(fichier)
    if not ok and not annule and not erreur_msg:
        erreur_msg = (
            f"Aucun chapitre téléchargé sur {total} — pages introuvables sur le site "
            "ou hébergeur d'images injoignable"
        )
    if annule:
        _safe_emit(queue, "dl_annule", {"nom": nom})
    _safe_emit(queue, "episode_done", {
        "nom": nom, "succes": ok, "skipped": False, "annule": annule, "erreur": erreur_msg,
    })
    _historique_ajouter(queue, nom, lang.upper(),
                        succes=int(ok), echoues=int(not ok and not annule))
    try:
        from engine.library.scanner import invalider_cache_librairie
        invalider_cache_librairie()
    except Exception:
        log.debug("library invalidation after scan failed", exc_info=True)
    _safe_emit(queue, "queue_updated", queue.statut())

async def _executer_un_episode(ep: dict[str, Any], i: int, total: int, titre: str, queue) -> str | None:
    try:
        return await _attendre_avec_budget(
            _traiter_un_episode(ep, i, total, titre, queue), queue
        )
    except TimeoutError:
        await _signaler_annulation_engine(queue)
        log.error("episode %d/%d: global timeout (%ds) — aborted", i + 1, total, MAX_EPISODE_DURATION)
        return "echoues"
    except DownloadCancelled:
        log.info("episode %d/%d annulé", i + 1, total)
        return None
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("exception on episode %d/%d", i + 1, total)
        return "echoues"

async def _traiter_episode(item: dict[str, Any], queue) -> None:
    from engine.config.logging_setup import section

    eps = _normaliser_episodes(item)
    if not eps:
        log.error("no episode to download in this item")
        _ep = item.get("ep")
        ep_obj = _ep if isinstance(_ep, dict) else {}
        titre_fallback = ep_obj.get("titre") or ep_obj.get("nom") or "Anime"
        _safe_emit(queue, "anime_done", {
            "titre": titre_fallback, "langue": "", "succes": 0, "echoues": 0,
            "skipped": 0, "annule": False, "erreur": "Aucun épisode fourni",
        })
        _safe_emit(queue, "queue_updated", queue.statut())
        return

    titre = eps[0].get("titre") or eps[0].get("nom") or "Anime"
    langue = eps[0].get("langue", "")
    total = len(eps)

    section(f"{titre}  —  {total} épisode(s) {langue}".strip())
    _safe_emit(queue, "anime_start", {"titre": titre, "langue": langue, "total": total})

    succes = echoues = skipped = 0
    t0 = time.time()
    interrompu = False

    _pf_tasks: set = set()
    try:
        for i, ep in enumerate(eps):
            if _est_annule(queue):
                log.warning("cancellation requested — stopping episode list")
                break
            await _attendre_reprise(queue)
            if _est_annule(queue):
                log.warning("cancellation requested — stopping episode list")
                break
            from engine.download._rate_limiter import cooldown_global
            if _PREFETCH_ENABLED and i + 1 < total and cooldown_global() <= 0:
                _pf = asyncio.ensure_future(prefetch_extraction(eps[i + 1], queue))
                _pf_tasks.add(_pf)
                _pf.add_done_callback(_pf_tasks.discard)
            # Lu par l'interface rouverte en cours de route : sans lui, elle ne
            # sait pas combien d'episodes de l'anime restent a telecharger.
            item["index_episode"] = i
            result = await _executer_un_episode(ep, i, total, titre, queue)
            if result is None:
                break

            if result == "skipped":
                skipped += 1
            elif result == "succes":
                succes += 1
            else:
                echoues += 1

            if not _est_annule(queue):
                await _pause_anti_ban(queue)
    except asyncio.CancelledError:
        interrompu = True
        raise
    finally:
        # Le bouton ✕ annule la tache du worker : sans cette cloture, la
        # CancelledError sortait d'ici en laissant les prefetch en vie et sans
        # jamais inscrire l'anime interrompu dans l'historique.
        for _t in list(_pf_tasks):
            _t.cancel()
        if interrompu:
            _cloturer_anime(queue, titre, langue, succes, echoues, skipped, True, t0)

    _pending = list(_pf_tasks)
    if _pending:
        await asyncio.gather(*_pending, return_exceptions=True)

    _cloturer_anime(queue, titre, langue, succes, echoues, skipped,
                    _est_annule(queue), t0)

def _cloturer_anime(queue, titre: str, langue: str, succes: int, echoues: int,
                    skipped: int, annule: bool, t0: float) -> None:
    from engine.config.logging_setup import summary

    entree = {
        "titre": titre, "langue": langue, "succes": succes,
        "echoues": echoues, "skipped": skipped, "annule": annule,
    }
    _historique_append(queue, entree)
    _safe_emit(queue, "anime_done", entree)
    _safe_emit(queue, "queue_updated", queue.statut())
    summary(title=f"{titre} {langue}".strip(), succes=succes, echoues=echoues,
            skipped=skipped, duration=time.time() - t0)
