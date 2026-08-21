"""Serialisation de /api/anime/librairie et niveau de compression gzip.

La route rendait un dict : FastAPI le repassait dans jsonable_encoder puis
json.dumps a chaque requete, et GZipMiddleware le recompressait au niveau 9,
le tout sur la boucle asyncio. Sur une librairie de 120 animes ces trois
etapes pesaient 32 des 35 ms de la reponse, cache pourtant chaud.
"""

import json

import pytest


@pytest.fixture
def cache_amorce(monkeypatch):
    import web.api.routes.anime.library as library
    from engine.library import scanner

    library._serialise = None
    donnees = {
        "animes": [
            {
                "nom": f"Animé n°{i} — été",
                "saisons": [{"nom": "Saison 01", "episodes": []}],
                "total_eps": 3,
                "total_size": 1.5,
            }
            for i in range(5)
        ],
        "total": 5,
        "tronque": False,
    }
    monkeypatch.setattr(scanner, "librairie_cache_get", lambda: donnees)
    yield donnees
    library._serialise = None


def _compter_encodages(monkeypatch):
    import web.api.routes.anime.library as library

    compteur = {"n": 0}
    reel = library._encoder

    def compte(donnees):
        compteur["n"] += 1
        return reel(donnees)

    monkeypatch.setattr(library, "_encoder", compte)
    return compteur


def test_cache_chaud_ne_reserialise_pas(client, cache_amorce, monkeypatch):
    client.get("/api/anime/librairie")
    compteur = _compter_encodages(monkeypatch)
    for _ in range(5):
        r = client.get("/api/anime/librairie")
        assert r.status_code == 200
    assert compteur["n"] == 0, (
        f"{compteur['n']} re-serialisations pour 5 requetes sur un cache inchange"
    )


def test_reponse_identique_au_dict_cache(client, cache_amorce):
    r = client.get("/api/anime/librairie")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == cache_amorce


def test_accents_preserves_en_utf8(client, cache_amorce):
    r = client.get("/api/anime/librairie")
    assert r.json()["animes"][0]["nom"] == "Animé n°0 — été"


def test_nouvel_objet_cache_reserialise(client, monkeypatch):
    import web.api.routes.anime.library as library
    from engine.library import scanner

    library._serialise = None
    etat = {"n": 0}

    def _get():
        etat["n"] += 1
        return {"animes": [], "total": etat["n"], "tronque": False}

    monkeypatch.setattr(scanner, "librairie_cache_get", _get)
    compteur = _compter_encodages(monkeypatch)
    premier = client.get("/api/anime/librairie").json()
    second = client.get("/api/anime/librairie").json()
    assert premier != second
    assert compteur["n"] == 2
    library._serialise = None


def test_memo_ne_retient_quun_seul_payload(client, monkeypatch):
    import web.api.routes.anime.library as library

    library._serialise = None
    library._payload_json({"a": 1})
    library._payload_json({"b": 2})
    assert library._serialise is not None
    assert json.loads(library._serialise[1]) == {"b": 2}
    library._serialise = None


def test_gzip_compresse_au_niveau_6():
    from web.api.app import GZipExceptSSE, create_app

    app = create_app()
    couches = []
    m = app.build_middleware_stack()
    while m is not None:
        couches.append(m)
        m = getattr(m, "app", None)
    gzip_layer = next((c for c in couches if isinstance(c, GZipExceptSSE)), None)
    assert gzip_layer is not None, "GZipExceptSSE absent de la pile"
    assert gzip_layer.gzipped.compresslevel == 6, (
        "le niveau 9 de Starlette bloque la boucle asyncio pendant la compression"
    )
