
import asyncio
import logging
import uuid

from engine.domain.exceptions import UnsafeUrlError
from engine.observability.context import task_context
from engine.utils.security import sanitize_filename, validate_external_url

log = logging.getLogger("engine.services.download_service")

class DownloadService:

    def __init__(self):
        from engine.download.queue import queue as _queue
        self._queue = _queue

    async def _enqueue(self, item: dict) -> int:
        if isinstance(item, dict) and not (
            isinstance(item.get("id"), str) and item.get("id")
        ):
            item["id"] = uuid.uuid4().hex[:6]
        return await self._queue.ajouter(item)

    async def ajouter_episode(self, item: dict) -> dict:
        ep = item.get("ep", {}) or {}

        titre = ep.get("titre", "Anime")
        ep["titre"] = sanitize_filename(titre)
        for e in item.get("episodes") or []:
            if isinstance(e, dict) and e.get("titre"):
                e["titre"] = sanitize_filename(e["titre"])

        position = await self._enqueue(item)
        with task_context(str(item.get("id", ""))):
            try:
                log.info(
                    f"Épisode ajouté à la queue : "
                    f"{ep.get('titre')} S{ep.get('saison', 1):02d}E{ep.get('episode', 0):03d}"
                )
            except Exception:
                log.info("Épisode ajouté à la queue : %s", ep.get("titre"))
        return {"ok": True, "position": position, "statut": self._queue.statut()}

    @staticmethod
    def _sanitize_headers(headers: dict) -> dict:
        propres: dict = {}
        if not isinstance(headers, dict):
            return propres
        for k, v in headers.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            if any(c in k or c in v for c in ("\r", "\n", "\0")):
                continue
            if len(k) > 100 or len(v) > 1000:
                continue
            propres[k] = v
        return propres

    async def ajouter_direct(self, url: str, nom: str, headers: dict | None = None) -> dict:
        try:
            url = await asyncio.to_thread(validate_external_url, url)
        except UnsafeUrlError as e:
            log.warning(f"URL directe refusée (sécurité) : {e}")
            return {"ok": False, "message": str(e)}

        nom = sanitize_filename(nom or "Episode")
        headers_propres = self._sanitize_headers(headers or {})

        item = {"_direct": True, "url_stream": url, "nom": nom,
                "headers_stream": headers_propres}
        position = await self._enqueue(item)
        with task_context(str(item.get("id", ""))):
            log.info(f"Téléchargement direct ajouté : {nom}")
        return {"ok": True, "position": position, "nom": nom}

    async def ajouter_scan(
        self, slug: str, oeuvre: str, lang: str, chapitres: list, nom: str | None = None
    ) -> dict:
        from engine.scraping.scan import normaliser_lang, slug_valide

        if not slug_valide(slug):
            return {"ok": False, "message": "Slug invalide"}
        oeuvre = (oeuvre or "").strip()
        if not oeuvre:
            return {"ok": False, "message": "Œuvre manquante"}
        chapitres = [str(c).strip() for c in (chapitres or []) if str(c).strip()][:5000]
        if not chapitres:
            return {"ok": False, "message": "Aucun chapitre sélectionné"}

        nom = sanitize_filename(nom or oeuvre)
        lang = normaliser_lang(lang)
        item = {"_scan": True, "slug": slug, "oeuvre": oeuvre,
                "lang": lang, "chapitres": chapitres, "nom": nom}
        position = await self._enqueue(item)
        with task_context(str(item.get("id", ""))):
            log.info(f"Scan ajouté à la queue : {nom} ({lang}) — {len(chapitres)} chapitre(s)")
        return {"ok": True, "position": position, "nom": nom, "total": len(chapitres)}

    def annuler(self) -> dict:
        ok = self._queue.annuler()
        return {"ok": ok, "statut": self._queue.statut()}

    def pause(self) -> dict:
        ok = self._queue.pause()
        return {"ok": ok}

    def reprendre(self) -> dict:
        ok = self._queue.reprendre()
        return {"ok": ok}

    def statut(self) -> dict:
        return self._queue.statut()

    def historique(self) -> list:
        return self._queue.statut().get("historique", [])

    def vider_historique(self) -> dict:
        self._queue.clear_history()
        return {"ok": True}

    def retirer(self, index: int) -> bool:
        return self._queue.retirer(index)

    def deplacer(self, from_: int, to: int) -> bool:
        return self._queue.deplacer(from_, to)

    def etat_breakers(self) -> dict:
        from engine.download._host_breakers import etat_breakers
        return etat_breakers()

download_service = DownloadService()
