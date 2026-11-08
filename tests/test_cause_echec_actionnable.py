"""Un téléchargement raté affichait « Aucune URL capturée » quelle que soit la cause
réelle — disque plein, moteurs en échec, scan sans page. Le champ `erreur` de
episode_done doit porter la vraie raison, en français, actionnable.
"""

import asyncio

from engine.download import pipeline
from engine.download.queue import CancelToken


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))

    def statut(self):
        return {}


def _ep(url="https://anime-sama.to/catalogue/x/saison1/vostfr?ep=1"):
    return {"titre": "Show", "saison": 1, "episode": 1, "langue": "VOSTFR", "url": url}


def _done_events(q):
    return [d for ev, d in q.events if ev == "episode_done"]


def _no_skip(monkeypatch):
    monkeypatch.setattr(pipeline, "_skip_existants_actif", lambda: False)
    monkeypatch.setattr(pipeline, "_fichier_existe", lambda d, n: False)


def _lecteurs_async(monkeypatch, lecteurs):
    async def get(url):
        return list(lecteurs)

    monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", get)


async def _rien(*a, **k):
    return None


def test_disque_plein_remonte_jusqu_a_l_utilisateur(monkeypatch):
    monkeypatch.setattr(pipeline, "_motif_url_refusee", lambda url: None)
    monkeypatch.setattr(pipeline, "_espace_disque_suffisant", lambda d: False)

    q = FakeQueue()
    with pipeline._collecte_causes() as causes:
        out = asyncio.run(
            pipeline._lancer_download_pipeline(
                "https://cdn.test/master.m3u8", "D:/dl", "ep", {}, q, "[x] E001",
                _rien, _rien, _rien,
            )
        )

    assert out is None
    assert causes
    assert "disque" in causes[-1].lower()


def test_les_trois_moteurs_en_echec_donnent_une_cause_explicite(monkeypatch):
    monkeypatch.setattr(pipeline, "_motif_url_refusee", lambda url: None)
    monkeypatch.setattr(pipeline, "_espace_disque_suffisant", lambda d: True)

    async def pool(fn, *args):
        return None

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    q = FakeQueue()
    with pipeline._collecte_causes() as causes:
        out = asyncio.run(
            pipeline._lancer_download_pipeline(
                "https://cdn.test/master.m3u8", "D:/dl", "ep", {}, q, "[x] E001",
                _rien, _rien, _rien,
            )
        )

    assert out is None
    assert causes
    assert "moteur" in causes[-1].lower()


def test_la_cause_remplace_le_message_generique(monkeypatch):
    _no_skip(monkeypatch)
    monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
    _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
    monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))

    async def ytdlp(*a, **k):
        pipeline._noter_cause("Espace disque insuffisant sur le disque de destination")
        return None

    monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", ytdlp)
    monkeypatch.setattr(pipeline, "_pipeline_playwright", _rien)

    q = FakeQueue()
    out = asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

    assert out == "echoues"
    erreur = _done_events(q)[-1]["erreur"]
    assert erreur == "Espace disque insuffisant sur le disque de destination"
    assert "Aucune URL capturée" not in erreur


def test_sans_cause_connue_le_message_par_defaut_est_conserve(monkeypatch):
    _no_skip(monkeypatch)
    monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)
    _lecteurs_async(monkeypatch, [{"src": "https://h/v", "host": "h"}])
    monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: (list(lec), []))
    monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", _rien)
    monkeypatch.setattr(pipeline, "_pipeline_playwright", _rien)

    q = FakeQueue()
    asyncio.run(pipeline._traiter_un_episode(_ep(), 0, 1, "Show", q))

    assert _done_events(q)[-1]["erreur"] == "Aucune URL capturée"


def test_direct_rate_donne_une_raison(monkeypatch):
    from engine.download import worker

    monkeypatch.setattr(worker, "_historique_ajouter", lambda *a, **k: None)

    async def pool(fn, *args):
        return None

    async def budget(coro, queue):
        return await coro

    monkeypatch.setattr(worker, "_run_in_pool", pool)
    monkeypatch.setattr(worker, "_attendre_avec_budget", budget)
    monkeypatch.setattr(pipeline, "_motif_url_refusee", lambda url: None)

    q = FakeQueue()
    item = {"_direct": True, "nom": "Ep", "url_stream": "https://cdn.test/x.m3u8"}
    asyncio.run(worker._traiter_direct(item, q))

    done = [d for ev, d in q.events if ev == "episode_done"]
    assert done[-1]["succes"] is False
    assert "téléchargé" in done[-1]["erreur"]


def test_scan_rate_donne_une_raison(monkeypatch):
    from engine.download import worker

    monkeypatch.setattr(worker, "_historique_ajouter", lambda *a, **k: None)

    async def pool(fn, *args):
        return None

    monkeypatch.setattr(worker, "_run_in_pool", pool)

    q = FakeQueue()
    item = {"_scan": True, "nom": "Berserk", "oeuvre": "berserk",
            "lang": "vf", "chapitres": ["1", "2"]}
    asyncio.run(worker._traiter_scan(item, q))

    done = [d for ev, d in q.events if ev == "episode_done"]
    assert done[-1]["succes"] is False
    assert done[-1]["erreur"]
    assert "chapitre" in done[-1]["erreur"].lower()


def test_le_prechargement_de_l_episode_suivant_ne_pollue_pas_les_causes(monkeypatch):
    # Avec DL_PREFETCH=1, l'extraction de l'episode suivant tourne pendant la
    # cascade de l'episode en cours : ses lecteurs refuses finissaient dans le
    # message d'echec de l'episode en cours.
    monkeypatch.setattr(pipeline, "RETRIES_EFFECTIFS", 1)

    async def scenario():
        prefetch_a_note = asyncio.Event()

        async def prechargement():
            pipeline._noter_cause("lecteur de l'épisode suivant refusé")
            prefetch_a_note.set()

        async def lecteurs_en_echec(*a, **k):
            await prefetch_a_note.wait()
            pipeline._noter_cause("sendvid : aucun fichier produit")
            return None

        monkeypatch.setattr(pipeline, "_ytdlp_sur_lecteurs", lecteurs_en_echec)
        monkeypatch.setattr(pipeline, "_extraire_et_telecharger", _rien)
        # Comme dans worker._traiter_episode : la tache part avant la cascade.
        tache = asyncio.ensure_future(prechargement())
        resultat = await pipeline._cascade_download(
            [{"src": "https://sendvid.com/x", "host": "sendvid"}], [], "d", "n", "ep", FakeQueue()
        )
        await tache
        return resultat

    fichier, erreur = asyncio.run(scenario())

    assert fichier is None
    assert erreur == "sendvid : aucun fichier produit"
