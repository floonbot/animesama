import asyncio
import json

import pytest

import engine.download.worker as worker
from engine.download.queue import DownloadQueue
from engine.download.store import DownloadStore


def _episodes(n):
    return [
        {
            "titre": "Un Titre D'Anime Assez Long Pour Peser",
            "saison": 1,
            "saison_nom": "Saison 01",
            "episode": i + 1,
            "langue": "VOSTFR",
            "url": f"https://exemple.test/anime/saison1/episode-{i + 1}",
        }
        for i in range(n)
    ]


def _item_episodes(n=500):
    eps = _episodes(n)
    return {"id": "abc123", "ep": eps[0], "episodes": eps}


def _item_scan(n=500):
    return {
        "id": "def456",
        "_scan": True,
        "slug": "un-scan",
        "oeuvre": "Un Scan",
        "nom": "Un Scan",
        "lang": "vf",
        "chapitres": [str(i + 1) for i in range(n)],
    }


@pytest.fixture
def q():
    return DownloadQueue()


def test_statut_tronque_les_episodes_et_expose_le_compteur(q):
    q._queue.append(_item_episodes(500))

    st = q.statut()
    projete = st["queue"][0]

    assert projete["nb_episodes"] == 500
    assert len(projete["episodes"]) == 1
    assert projete["episodes"][0] == _episodes(1)[0]


def test_statut_tronque_les_chapitres_et_expose_le_compteur(q):
    q._queue.append(_item_scan(500))

    projete = q.statut()["queue"][0]

    assert projete["nb_chapitres"] == 500
    assert projete["chapitres"] == []


def test_statut_reste_sous_8_ko_pour_500_episodes(q):
    q._queue.append(_item_episodes(500))

    taille = len(json.dumps(q.statut()))

    assert taille < 8192, f"payload de {taille} octets"


def test_la_file_interne_garde_la_charge_complete(q):
    q._queue.append(_item_episodes(500))

    q.statut()

    assert len(q._queue[0]["episodes"]) == 500
    assert q._queue[0] is not q.statut()["queue"][0]


def test_en_cours_est_projete_aussi(q):
    q._current = _item_episodes(500)

    en_cours = q.statut()["en_cours"]

    assert en_cours["nb_episodes"] == 500
    assert len(en_cours["episodes"]) == 1
    assert q._current is not None
    assert len(q._current["episodes"]) == 500


def test_projection_preserve_le_contrat_du_front(q):
    q._queue.append(_item_episodes(3))
    q._queue.append(_item_scan(4))

    eps_item, scan_item = q.statut()["queue"]

    assert eps_item["id"] == "abc123"
    assert eps_item["ep"]["titre"] == "Un Titre D'Anime Assez Long Pour Peser"
    assert eps_item["episodes"][0]["langue"] == "VOSTFR"
    assert eps_item["episodes"][0]["saison_nom"] == "Saison 01"
    assert eps_item["episodes"][0]["episode"] == 1

    assert scan_item["_scan"] is True
    assert scan_item["nom"] == "Un Scan"
    assert scan_item["lang"] == "vf"
    assert scan_item["nb_chapitres"] == 4


def test_historique_non_projete(q):
    q._history.append({"nom": "A", "succes": True, "episodes": _episodes(3)})

    hist = q.statut()["historique"]

    assert len(hist[0]["episodes"]) == 3
    assert "nb_episodes" not in hist[0]


def test_item_sans_liste_reste_intact(q):
    q._queue.append({"id": "x", "_direct": True, "nom": "Episode"})

    projete = q.statut()["queue"][0]

    assert projete["nb_episodes"] == 0
    assert projete["nb_chapitres"] == 0
    assert projete["nom"] == "Episode"


def test_le_worker_recoit_les_500_episodes_apres_aller_retour_store(tmp_path, monkeypatch):
    store = DownloadStore(tmp_path / "d.db")
    vus: list[int] = []

    async def _fake(item, q):
        vus.append(len(item["episodes"]))

    monkeypatch.setattr(worker, "traiter_item", _fake)

    try:
        source = DownloadQueue()
        source._store = store
        source._queue.append(_item_episodes(500))
        source._persist_queue()

        cible = DownloadQueue()
        cible._store = store
        cible.restore()

        assert len(cible._queue[0]["episodes"]) == 500
        assert cible.statut()["queue"][0]["nb_episodes"] == 500

        asyncio.run(cible._run())

        assert vus == [500]
    finally:
        store.close()
