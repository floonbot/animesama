
import asyncio
import contextvars
import logging
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from engine.config.settings import DL_MAX_RETRIES, DL_RETRY_DELAY, get_downloads_dir
from engine.domain.exceptions import DownloadCancelled
from engine.download._debit import PolitiqueDebit
from engine.download._domain_strategy import get_domain, partition_lecteurs, reecrire_domaine
from engine.download._helpers import ESPACE_DISQUE_MIN_MB
from engine.download._helpers import (
    espace_disque_suffisant as _espace_disque_suffisant,
)
from engine.download._helpers import (
    fichier_existe as _fichier_existe,
)
from engine.download._helpers import (
    skip_existants_actif as _skip_existants_actif,
)
from engine.download._host_breakers import get_breaker, host_disponible
from engine.download._hotes_bloques import (
    hote_bloque,
    marquer_bloque,
    sans_hotes_bloques,
    sonder_blocage,
)
from engine.download._rate_limiter import (
    cooldown_global,
    domain_apply_penalty,
    domain_en_penalite,
    domain_mark_used,
    domain_penalty,
    domain_wait,
    hote_throttle,
)
from engine.download._runtime import _est_annule, _run_in_pool, _safe_emit
from engine.observability.context import task_context
from engine.scraping.parser import dossier_saison, nettoyer_titre, nom_fichier
from engine.scraping.site.animessama import SITE_URL
from engine.utils.circuit_breaker import CircuitOpenError

log = logging.getLogger("engine.download.pipeline")

def _record_host(host: str, outcome: str) -> None:
    try:
        from engine.observability.metrics import metrics
        metrics.incr(f"host_{outcome}_{(host or 'inconnu').lower()}", 1)
    except Exception:
        log.debug("metrics host record failed", exc_info=True)

def _record_via(link: str) -> None:
    try:
        from engine.observability.metrics import metrics
        metrics.incr(f"extract_via_{link}", 1)
    except Exception:
        log.debug("metrics extract_via record failed", exc_info=True)

RETRIES_EFFECTIFS = max(1, min(int(DL_MAX_RETRIES or 1), 20))
DELAI_RETRY_EFFECTIF = max(0, min(int(DL_RETRY_DELAY or 3), 60))
TIMEOUT_LECTEUR_SEQ = 20
TIMEOUT_LECTEUR_PAR = 20

_PREFETCH_ENABLED = os.getenv("DL_PREFETCH", "").strip().lower() in ("1", "true", "yes")
_PREFETCH_DELAY = 5.0
_EXT_CACHE_TTL = 120.0
_ext_cache: dict[str, tuple[float, dict]] = {}
_ext_inflight: dict = {}

class _SilentQueue:
    def __init__(self, real) -> None:
        self._cancelled = getattr(real, "_cancelled", None)

    def emit(self, *a, **k) -> None:
        pass

def _ext_cache_take(ep_url: str) -> dict | None:
    item = _ext_cache.pop(ep_url, None)
    if item and (time.time() - item[0]) < _EXT_CACHE_TTL:
        return item[1]
    return None

def _ext_cache_set(ep_url: str, result: dict) -> None:
    if len(_ext_cache) > 50:
        _ext_cache.clear()
    _ext_cache[ep_url] = (time.time(), result)

async def prefetch_extraction(ep: dict[str, Any], queue) -> None:
    if not _PREFETCH_ENABLED:
        return
    ep_url = ep.get("url", "")
    if not ep_url or ep_url in _ext_cache or ep_url in _ext_inflight:
        return
    fut = asyncio.get_running_loop().create_future()
    _ext_inflight[ep_url] = fut
    result = None
    try:
        await asyncio.sleep(_PREFETCH_DELAY)
        if _est_annule(queue):
            return
        from engine.scraping.scraper import get_lecteurs_async
        lecteurs = await get_lecteurs_async(ep_url)
        if not lecteurs or _est_annule(queue):
            return
        ytdlp_lecteurs, playwright_lecteurs = partition_lecteurs(lecteurs)
        if ytdlp_lecteurs or not playwright_lecteurs:
            return
        extrait = await asyncio.wait_for(
            _pipeline_playwright(playwright_lecteurs, "prefetch", _SilentQueue(queue)),
            timeout=TIMEOUT_LECTEUR_PAR + (len(playwright_lecteurs) + 1) * TIMEOUT_LECTEUR_SEQ,
        )
        if extrait and extrait.get("url") and not _est_annule(queue):
            result = extrait
            _ext_cache_set(ep_url, extrait)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.debug("prefetch extraction failed", exc_info=True)
    finally:
        _ext_inflight.pop(ep_url, None)
        if not fut.done():
            fut.set_result(result)

async def _traiter_un_episode(ep: dict[str, Any], index: int, total: int, titre_anime: str, queue) -> str:
    dl_id = uuid.uuid4().hex[:6]
    t0 = time.time()
    with task_context(dl_id):
        try:
            return await _traiter_un_episode_impl(ep, index, total, titre_anime, queue, dl_id)
        finally:
            try:
                from engine.observability.metrics import metrics
                metrics.observe("lat_episode_s", time.time() - t0)
            except Exception:
                log.debug("metrics episode latency failed", exc_info=True)

async def _extraire_et_telecharger(
    lecteurs: list[dict[str, Any]], dossier: str, nom_ep: str, ep_label: str, queue
) -> str | None:
    from engine.download.methods.ffmpeg_engine import ffmpeg_download
    from engine.download.methods.nm3u8dl import nm3u8dl_download
    from engine.download.methods.ytdlp_engine import ytdlp_download

    # Bloque en cours d'episode (le partage des lecteurs est fait avant) : le
    # navigateur prendrait le meme refus.
    lecteurs = sans_hotes_bloques(lecteurs)
    if not lecteurs:
        return None
    result = await _pipeline_playwright(lecteurs, ep_label, queue)
    if result:
        return await _lancer_download_pipeline(
            result["url"], dossier, nom_ep, result.get("headers", {}),
            queue, ep_label, nm3u8dl_download, ytdlp_download, ffmpeg_download,
        )
    return None

def _bucket_sniff_autorise(lecteurs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if cooldown_global() > 0:
        return []
    autorises = []
    for l in lecteurs:
        dom = get_domain(l.get("src", ""))
        if domain_en_penalite(dom) or hote_throttle(dom):
            continue
        autorises.append(l)
    return autorises

# Les moteurs et les gardes echouent loin du point ou le message est emis :
# sans ce relais, `episode_done.erreur` affichait toujours "Aucune URL capturée",
# quelle que soit la cause reelle (disque plein, blackhole DNS, moteurs a plat).
#
# Une liste par cascade, portee par le contexte et non par le module : le
# prechargement de l'episode suivant (DL_PREFETCH) tourne pendant la cascade en
# cours, et ses lecteurs refuses finissaient dans le message de l'episode en
# cours. Sa tache est creee avant la cascade : elle ne voit pas cette liste.
# Les threads de asyncio.to_thread, eux, heritent du contexte, donc de la liste.
_causes_en_cours: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "causes_echec", default=None
)

@contextmanager
def _collecte_causes() -> Iterator[list[str]]:
    causes: list[str] = []
    jeton = _causes_en_cours.set(causes)
    try:
        yield causes
    finally:
        _causes_en_cours.reset(jeton)

def _noter_cause(motif: str) -> None:
    causes = _causes_en_cours.get()
    if causes is None or not motif or motif in causes:
        return
    causes.append(motif)
    del causes[:-5]

def _resumer_causes(causes: list[str], limite: int = 400) -> str:
    """Toutes les causes, pas seulement la derniere.

    Quatre lecteurs peuvent echouer pour quatre raisons differentes ; n'en
    montrer qu'une envoyait l'utilisateur diagnostiquer la mauvaise. Le message
    part en toast, donc il reste borne : ce qui ne tient pas est annonce en
    nombre plutot que tronque en silence.
    """
    uniques = list(dict.fromkeys(c.strip() for c in causes if c and c.strip()))
    if not uniques:
        return ""
    if len(uniques) == 1:
        return uniques[0][:limite]
    resume = ""
    for i, cause in enumerate(uniques):
        candidat = cause if not resume else f"{resume} · {cause}"
        if len(candidat) > limite:
            restantes = len(uniques) - i
            marque = f" (+{restantes} autre{'s' if restantes > 1 else ''})"
            return (resume + marque) if resume else cause[: limite - len(marque)] + marque
        resume = candidat
    return resume

def _motif_url_refusee(url: str) -> str | None:
    from engine.domain.exceptions import UnsafeUrlError
    from engine.utils import security

    if security.is_safe_url(url):
        return None
    try:
        security.validate_external_url(url)
    except UnsafeUrlError as e:
        motif = str(e)
    else:
        motif = "URL non autorisée"
    _noter_cause(motif)
    return motif

async def _cascade_download(
    ytdlp_lecteurs: list[dict[str, Any]],
    playwright_lecteurs: list[dict[str, Any]],
    dossier: str,
    nom_ep: str,
    ep_label: str,
    queue,
) -> tuple[str | None, str]:
    with _collecte_causes() as causes:
        fichier, erreur = await _cascade_tentatives(
            ytdlp_lecteurs, playwright_lecteurs, dossier, nom_ep, ep_label, queue
        )
    if not fichier and causes:
        erreur = _resumer_causes(causes)
    return fichier, erreur

async def _cascade_tentatives(
    ytdlp_lecteurs: list[dict[str, Any]],
    playwright_lecteurs: list[dict[str, Any]],
    dossier: str,
    nom_ep: str,
    ep_label: str,
    queue,
) -> tuple[str | None, str]:
    fichier = None
    erreur = "Aucune URL capturée"
    politique = PolitiqueDebit()

    for tentative in range(1, RETRIES_EFFECTIFS + 1):
        if _est_annule(queue):
            break
        try:
            if ytdlp_lecteurs and not fichier:
                politique.alternatives = len(playwright_lecteurs)
                fichier = await _ytdlp_sur_lecteurs(
                    ytdlp_lecteurs, dossier, nom_ep, ep_label, queue,
                    referer=SITE_URL + "/", politique=politique,
                )
            if fichier:
                break

            if ytdlp_lecteurs and not fichier and not playwright_lecteurs:
                fichier = await _extraire_et_telecharger(
                    ytdlp_lecteurs, dossier, nom_ep, ep_label, queue
                )
                if fichier:
                    break

            if playwright_lecteurs:
                fichier = await _extraire_et_telecharger(
                    playwright_lecteurs, dossier, nom_ep, ep_label, queue
                )
                if fichier:
                    break
                fichier = await _ytdlp_sur_lecteurs(
                    playwright_lecteurs, dossier, nom_ep, ep_label, queue,
                    referer=SITE_URL + "/",
                )
            if fichier:
                break

            if ytdlp_lecteurs and playwright_lecteurs and not fichier:
                sniff_bucket = _bucket_sniff_autorise(ytdlp_lecteurs)
                if sniff_bucket:
                    fichier = await _extraire_et_telecharger(
                        sniff_bucket, dossier, nom_ep, ep_label, queue
                    )
                    if fichier:
                        break

            if not ytdlp_lecteurs and not playwright_lecteurs:
                erreur = "Aucun lecteur valide"
        except DownloadCancelled:
            raise
        except RuntimeError as exc:
            erreur = str(exc)[:200]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("%s attempt %d failed: %s", ep_label, tentative, exc)
            erreur = str(exc)[:200]

        if tentative < RETRIES_EFFECTIFS and not fichier:
            await asyncio.sleep(DELAI_RETRY_EFFECTIF)

    return fichier, erreur

async def _essayer_prefetch(
    ep_url: str, dossier: str, nom_ep: str, ep_label: str, queue
) -> str | None:
    from engine.download.methods.ffmpeg_engine import ffmpeg_download
    from engine.download.methods.nm3u8dl import nm3u8dl_download
    from engine.download.methods.ytdlp_engine import ytdlp_download

    _pf = None
    _inflight = _ext_inflight.get(ep_url)
    if _inflight is not None:
        try:
            _pf = await asyncio.wait_for(_inflight, timeout=TIMEOUT_LECTEUR_PAR + 8)
        except Exception:
            _pf = None
    if _pf is None:
        _pf = _ext_cache_take(ep_url)
    if _pf and _pf.get("url"):
        return await _lancer_download_pipeline(
            _pf["url"], dossier, nom_ep, _pf.get("headers", {}),
            queue, ep_label, nm3u8dl_download, ytdlp_download, ffmpeg_download,
        )
    return None

async def _traiter_un_episode_impl(
    ep: dict[str, Any], index: int, total: int, titre_anime: str, queue, dl_id: str
) -> str:
    from engine.scraping.scraper import get_lecteurs_async

    saison = ep.get("saison", 1)
    saison_nom = ep.get("saison_nom", "")
    ep_num = ep.get("episode", 0)
    langue = ep.get("langue", "")
    ep_url = ep.get("url", "")
    dossier_sais = dossier_saison(saison_nom, saison)
    ep_label = f"[{dl_id}] {dossier_sais} E{int(ep_num):03d}" + (f" {langue}" if langue else "")
    nom_ep = nom_fichier(ep["titre"], saison, ep_num, langue, saison_nom)
    dossier = str(get_downloads_dir() / nettoyer_titre(ep["titre"]) / dossier_sais)

    log.info("Episode %s  (%d/%d)", ep_label, index + 1, total)

    if not ep_url:
        log.error("%s: missing episode URL", ep_label)
        _safe_emit(queue, "episode_done", {
            "ep": ep_label, "succes": False, "erreur": "URL manquante", "skipped": False,
        })
        return "echoues"

    skip_existants = _skip_existants_actif()
    if skip_existants and _fichier_existe(dossier, nom_ep):
        log.info("%s already present — skipped", ep_label)
        _safe_emit(queue, "episode_done", {"ep": ep_label, "skipped": True, "succes": True})
        return "skipped"

    _safe_emit(queue, "episode_start", {
        "titre": titre_anime, "ep": ep_label, "index": index, "total": total,
    })

    if _PREFETCH_ENABLED:
        try:
            fichier = await _essayer_prefetch(ep_url, dossier, nom_ep, ep_label, queue)
            if fichier:
                log.info("%s done (prefetched)", ep_label)
                _safe_emit(queue, "episode_done", {"ep": ep_label, "succes": True, "skipped": False})
                return "succes"
        except (DownloadCancelled, asyncio.CancelledError):
            raise
        except Exception:
            log.debug("%s: prefetched path failed → normal", ep_label, exc_info=True)

    try:
        lecteurs = await get_lecteurs_async(ep_url)
    except Exception:
        log.warning("player retrieval failed for %s", ep_label, exc_info=True)
        lecteurs = []

    if not lecteurs:
        log.error("%s: no player found on the page", ep_label)
        _safe_emit(queue, "episode_done", {
            "ep": ep_label, "succes": False, "erreur": "Aucun lecteur sur la page", "skipped": False,
        })
        return "echoues"

    ytdlp_lecteurs, playwright_lecteurs = partition_lecteurs(lecteurs)
    log.info("%s: %d lecteur(s) disponible(s) — essai en cascade jusqu'a reussite", ep_label, len(lecteurs))
    fichier, erreur = await _cascade_download(
        ytdlp_lecteurs, playwright_lecteurs, dossier, nom_ep, ep_label, queue
    )

    if fichier:
        log.info("%s done", ep_label)
        _safe_emit(queue, "episode_done", {"ep": ep_label, "succes": True, "skipped": False})
        return "succes"
    log.error("%s failed — %s", ep_label, erreur)
    _safe_emit(queue, "episode_done", {"ep": ep_label, "succes": False, "erreur": erreur, "skipped": False})
    return "echoues"

async def _ytdlp_sur_lecteurs(
    lecteurs: list[dict[str, Any]], dossier: str, nom_ep: str, ep_label: str, queue,
    referer: str = "", politique: PolitiqueDebit | None = None,
) -> str | None:
    lecteurs_ok = [l for l in lecteurs if isinstance(l, dict) and l.get("src")]
    if not lecteurs_ok:
        return None

    lents: list[dict[str, Any]] = []
    fichier = await _passe_ytdlp(
        lecteurs_ok, dossier, nom_ep, ep_label, queue, referer, politique, lents
    )
    if fichier or not lents:
        return fichier
    # Un lecteur lent reste un lecteur : l'abandonner definitivement echangerait
    # 17 minutes d'attente contre un echec sec.
    log.info("%s: aucun lecteur rapide n'a abouti — reprise du/des lecteur(s) lent(s)", ep_label)
    # Ces lecteurs-la ont deja ete comptes a la premiere passe. Les recompter
    # rendait taux_succes_pct pessimiste — 50 % pour un lecteur qui a abouti —
    # et c'est cette valeur qui declenche l'alerte « hote degrade » du diagnostic.
    return await _passe_ytdlp(
        lents, dossier, nom_ep, ep_label, queue, referer, None, [],
        compter_tentative=False,
    )

async def _passe_ytdlp(
    lecteurs_ok: list[dict[str, Any]], dossier: str, nom_ep: str, ep_label: str, queue,
    referer: str, politique: PolitiqueDebit | None, lents: list[dict[str, Any]],
    compter_tentative: bool = True,
) -> str | None:
    from engine.download.extractor.registry import get_extractor
    from engine.download.methods.ytdlp_engine import RateLimitError, ytdlp_download

    cancelled = getattr(queue, "_cancelled", None)

    for i, lec in enumerate(lecteurs_ok, 1):
        if _est_annule(queue):
            break
        src = reecrire_domaine(lec.get("src", ""))
        domain = get_domain(src)
        host = lec.get("host", domain or "?")
        ext = get_extractor(src)
        if ext.name != "generic" and not ext.prefer_ytdlp:
            log.debug("%s: yt-dlp ignoré (%s non géré par yt-dlp)", ep_label, host)
            continue
        if not host_disponible(host):
            log.debug("%s: yt-dlp ignoré, circuit ouvert (%s)", ep_label, host)
            continue
        if hote_throttle(domain):
            log.debug("%s: yt-dlp ignoré, hôte throttlé (%s)", ep_label, host)
            continue
        if hote_bloque(domain):
            log.debug("%s: yt-dlp ignoré, hôte bloqué pour cette connexion (%s)", ep_label, host)
            continue
        motif = await asyncio.to_thread(_motif_url_refusee, src)
        if motif:
            log.warning("%s: lecteur refusé (%s) — %s", ep_label, host, motif)
            continue
        log.info("%s: lecteur %d/%d via yt-dlp (%s)", ep_label, i, len(lecteurs_ok), host)
        if compter_tentative:
            _record_host(host, "attempt")
        await domain_wait(domain)
        if _est_annule(queue):
            break

        _safe_emit(queue, "episode_progress", {"pct": 0, "line": f"Téléchargement depuis {host}…", "ep": ep_label})

        def on_progress(pct, ligne, _label=ep_label):
            _safe_emit(queue, "episode_progress", {"pct": pct, "line": ligne, "ep": _label})

        headers = {"referer": referer} if referer else {}
        surveillant = (
            politique.surveillant(cancelled, domain, len(lecteurs_ok) - i)
            if politique is not None else None
        )
        try:
            domain_mark_used(domain)
            fichier = await _run_in_pool(
                ytdlp_download, src, dossier, nom_ep, headers,
                surveillant if surveillant is not None else cancelled, on_progress,
            )
            if fichier:
                get_breaker(host)._on_success()
                _record_host(host, "ok")
                _record_via("ytdlp_direct")
                return fichier
            # yt-dlp sort en code 0 sans produire de fichier : il rend None sans
            # lever, et la boucle passait au lecteur suivant sans rien noter. Le
            # disjoncteur restait donc ferme pour toujours, et l'hote reprenait
            # un tour de cascade a chaque episode.
            if not _est_annule(queue):
                get_breaker(host)._on_failure(RuntimeError("aucun fichier produit"))
                _noter_cause(f"{host} : aucun fichier produit")
        except DownloadCancelled:
            if (
                politique is None
                or surveillant is None
                or not surveillant.abandon_lenteur
                or _est_annule(queue)
            ):
                raise
            politique.enregistrer_abandon(domain)
            lents.append(lec)
            _noter_cause(surveillant.motif)
            log.warning("%s: %s", ep_label, surveillant.motif)
            _safe_emit(queue, "episode_progress", {
                "pct": 0, "line": f"{host} trop lent → lecteur suivant…", "ep": ep_label,
            })
            continue
        except RateLimitError as exc:
            get_breaker(host)._on_failure(exc)
            # Un refus de l'adresse IP n'est pas une limite de debit : ni
            # penalite a attendre, ni « ban » qui declencherait la pause globale.
            if await asyncio.to_thread(sonder_blocage, src):
                marquer_bloque(domain)
                _noter_cause(f"{host} refuse cette connexion (403 « administrative rules ») — "
                             "écarté pour la session")
                _safe_emit(queue, "episode_progress", {
                    "pct": 0, "line": f"{host} refuse cette connexion → lecteur suivant…", "ep": ep_label,
                })
                continue
            domain_apply_penalty(domain)
            log.warning("%s: 403 on %s → penalty %.0fs, next player", ep_label, host, domain_penalty(domain))
            _safe_emit(queue, "episode_progress", {
                "pct": 0, "line": f"{host} occupé → lecteur de secours…", "ep": ep_label,
            })
        except RuntimeError as exc:
            get_breaker(host)._on_failure(exc)
            log.debug("%s: yt-dlp %s error", ep_label, host, exc_info=True)
        except Exception as exc:
            get_breaker(host)._on_failure(exc)
            log.debug("%s: yt-dlp %s error", ep_label, host, exc_info=True)
    return None

async def _pipeline_playwright(lecteurs: list[dict[str, Any]], ep_label: str, queue) -> dict | None:
    t0 = time.time()
    try:
        return await _pipeline_playwright_impl(lecteurs, ep_label, queue)
    finally:
        try:
            from engine.observability.metrics import metrics
            metrics.incr("temps_interception_ms", int((time.time() - t0) * 1000))
            metrics.incr("interception_count", 1)
        except Exception:
            pass

async def _lecteurs_uniques_safe(
    lecteurs: list[dict[str, Any]], ep_label: str
) -> list[dict[str, Any]]:

    seen_src: set[str] = set()
    lecteurs_ok = []
    for l in lecteurs:
        if not (isinstance(l, dict) and l.get("src")):
            continue
        src = l["src"]
        if src in seen_src:
            continue
        seen_src.add(src)
        lecteurs_ok.append(l)
    _motifs = await asyncio.gather(*[
        asyncio.to_thread(_motif_url_refusee, lec.get("src", "")) for lec in lecteurs_ok
    ])
    lecteurs_safe = []
    for lec, motif in zip(lecteurs_ok, _motifs, strict=True):
        if motif is None:
            lecteurs_safe.append(lec)
        else:
            log.warning("%s: lecteur refusé (%s) — %s", ep_label, lec.get("host", "?"), motif)
    return lecteurs_safe

async def _essai_parallele(lecteurs_ok: list[dict[str, Any]]) -> dict | None:
    from engine.download.interceptor import intercepter_lecteurs_parallele

    lecteurs_ok = [
        l for l in lecteurs_ok
        if host_disponible(l.get("host", "?")) and not hote_throttle(get_domain(l.get("src", "")))
    ]
    if not lecteurs_ok:
        return None

    won_host = {"h": "?"}

    def _on_win(src: str) -> None:
        won_host["h"] = next(
            (l.get("host", "?") for l in lecteurs_ok if l.get("src") == src), "?"
        )

    result = await intercepter_lecteurs_parallele(
        lecteurs_ok, timeout=TIMEOUT_LECTEUR_PAR, on_win=_on_win
    )
    if result:
        if won_host["h"] != "?":
            get_breaker(won_host["h"])._on_success()
            _record_host(won_host["h"], "attempt")
            _record_host(won_host["h"], "ok")
        _record_via("network_parallel")
        return result
    return None

async def _essai_sequentiel(lecteurs_ok: list[dict[str, Any]], ep_label: str, queue) -> dict | None:
    from engine.download.interceptor import intercepter_lecteur

    nb = len(lecteurs_ok)

    async def _intercepter_strict(s, t):
        r = await intercepter_lecteur(s, t)
        if r is None:
            raise RuntimeError("aucun flux livré")
        return r

    for idx, lec in enumerate(lecteurs_ok, 1):
        if _est_annule(queue):
            break
        src = lec.get("src", "")
        host = lec.get("host", "?")
        if not host_disponible(host):
            continue
        if hote_throttle(get_domain(src)):
            continue
        log.info("%s: lecteur %d/%d via Playwright (%s)", ep_label, idx, nb, host)
        _safe_emit(queue, "episode_progress", {
            "pct": 0, "line": f"Recherche de la vidéo {idx}/{nb} ({host})…", "ep": ep_label,
        })
        _record_host(host, "attempt")
        try:
            result = await get_breaker(host).call(_intercepter_strict, src, TIMEOUT_LECTEUR_SEQ)
            if result:
                _record_host(host, "ok")
                _record_via("network_seq")
                return result
        except CircuitOpenError:
            pass
        except RuntimeError:
            log.debug("%s: %s error", ep_label, host, exc_info=True)
        except Exception:
            log.debug("%s: %s Playwright error", ep_label, host, exc_info=True)
    return None

async def _essai_forensic(lecteurs_ok: list[dict[str, Any]], ep_label: str, queue) -> dict | None:
    try:
        from engine.download.extractor.browser_extractor import extraire_flux
    except ImportError:
        return None

    for lec in lecteurs_ok:
        if _est_annule(queue):
            break
        src = lec.get("src", "")
        host = lec.get("host", "?")
        if hote_throttle(get_domain(src)):
            continue
        _safe_emit(queue, "episode_progress", {
            "pct": 0, "line": f"Extraction avancée JS : {host}…", "ep": ep_label,
        })
        _record_host(host, "attempt")
        try:
            extraction = await extraire_flux(src, timeout=TIMEOUT_LECTEUR_SEQ, mode="forensic")
            if extraction and extraction.get("best"):
                best = extraction["best"]
                _record_host(host, "ok")
                _record_via("browser_forensic")
                return {"url": best["url"], "headers": best.get("headers", {})}
        except Exception:
            log.debug("%s: browser_extractor %s error", ep_label, host, exc_info=True)
    return None

async def _pipeline_playwright_impl(lecteurs: list[dict[str, Any]], ep_label: str, queue) -> dict | None:
    lecteurs_ok = await _lecteurs_uniques_safe(lecteurs, ep_label)
    if not lecteurs_ok:
        return None

    result = await _essai_parallele(lecteurs_ok)
    if result:
        return result

    result = await _essai_sequentiel(lecteurs_ok, ep_label, queue)
    if result:
        return result

    return await _essai_forensic(lecteurs_ok, ep_label, queue)

async def _lancer_download_pipeline(url, dossier, nom_ep, headers, queue, ep_label,
                                    fn_nm3u8dl, fn_ytdlp, fn_ffmpeg) -> str | None:
    motif = await asyncio.to_thread(_motif_url_refusee, url)
    if motif:
        log.error("%s: URL capturée refusée — %s", ep_label, motif)
        return None

    def on_progress(pct, ligne, _label=ep_label):
        _safe_emit(queue, "episode_progress", {"pct": pct, "line": ligne, "ep": _label})

    cancelled = getattr(queue, "_cancelled", None)

    if not _espace_disque_suffisant(dossier):
        log.error("%s: insufficient disk space — download cancelled", ep_label)
        on_progress(0, "Espace disque insuffisant")
        _noter_cause(
            f"Espace disque insuffisant sur « {dossier} » "
            f"(moins de {ESPACE_DISQUE_MIN_MB} Mo libres) — libère de la place "
            "ou change le dossier de téléchargement dans les réglages"
        )
        return None

    try:
        fichier = await _run_in_pool(fn_nm3u8dl, url, dossier, nom_ep, headers, cancelled, on_progress)
        if fichier:
            return fichier
    except RuntimeError:
        raise
    except Exception:
        log.warning("%s: N_m3u8DL-RE exception → yt-dlp", ep_label, exc_info=True)

    if _est_annule(queue):
        raise DownloadCancelled()

    try:
        from engine.download.methods.ytdlp_engine import RateLimitError as _RLE
        fichier = await _run_in_pool(fn_ytdlp, url, dossier, nom_ep, headers, cancelled, on_progress)
        if fichier:
            return fichier
    except _RLE:
        domain = get_domain(url)
        if domain:
            domain_apply_penalty(domain)
        log.warning("%s: yt-dlp 403 (%s) → ffmpeg", ep_label, domain)
    except RuntimeError:
        raise
    except Exception:
        log.warning("%s: yt-dlp exception → ffmpeg", ep_label, exc_info=True)

    if _est_annule(queue):
        raise DownloadCancelled()

    try:
        fichier = await _run_in_pool(fn_ffmpeg, url, dossier, nom_ep, headers, cancelled, on_progress)
        if fichier:
            return fichier
        log.error("%s: all 3 engines failed", ep_label)
    except RuntimeError:
        raise
    except Exception:
        log.error("%s: ffmpeg exception", ep_label, exc_info=True)
    _noter_cause(
        "Flux vidéo trouvé mais aucun moteur n'a réussi à le télécharger "
        "(N_m3u8DL-RE, yt-dlp et ffmpeg ont tous échoué) — l'hébergeur bloque "
        "peut-être le téléchargement, réessaie plus tard"
    )
    return None
