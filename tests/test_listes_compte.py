"""C12.a — les quatre listes du compte anime-sama, pas seulement les favoris.

Formes relevees sur get-data.php avec une session valide (2026-08-10) :
`favorites`, `watchlist` et `viewed` sont trois dicts de tableaux paralleles
identiques ; `history` en differe — ses URL designent une saison et une langue
(`/catalogue/hell-mode/saison2/vostfr/`), pas une oeuvre.
"""

from engine.scraping.parser.profile import parse_favoris_api
from engine.scraping.site.animessama import SITE_URL


def _liste(*noms):
    return {
        "nom": list(noms),
        "url": [f"/catalogue/{n.lower().replace(' ', '-')}/" for n in noms],
        "img": ["" for _ in noms],
    }


def test_union_des_listes_avec_appartenance():
    data = {
        "logged_in": True,
        "favorites": _liste("Iruma", "Rearguard"),
        "watchlist": _liste("Rearguard", "One Piece"),
        "viewed": _liste("Bleach"),
    }
    res = parse_favoris_api(data)
    par_nom = {a["nom"]: a for a in res}

    assert set(par_nom) == {"Iruma", "Rearguard", "One Piece", "Bleach"}
    assert par_nom["Iruma"]["listes"] == ["favoris"]
    assert par_nom["Rearguard"]["listes"] == ["favoris", "watchlist"]
    assert par_nom["One Piece"]["listes"] == ["watchlist"]
    assert par_nom["Bleach"]["listes"] == ["vus"]


def test_favoris_restent_en_tete_de_l_union():
    data = {
        "logged_in": True,
        "favorites": _liste("Alpha"),
        "watchlist": _liste("Beta"),
    }
    assert [a["nom"] for a in parse_favoris_api(data)] == ["Alpha", "Beta"]


def test_historique_rejoint_l_oeuvre_malgre_l_url_de_saison():
    data = {
        "logged_in": True,
        "favorites": _liste("Hell Mode"),
        "history": {
            "nom": ["Hell Mode"],
            "url": ["/catalogue/hell-mode/saison2/vostfr/"],
            "img": [""],
            "type": ["Saison 2"],
            "lang": ["VOSTFR"],
            "ep": ["Episode 6"],
        },
    }
    res = parse_favoris_api(data)
    assert len(res) == 1
    assert res[0]["listes"] == ["favoris", "historique"]
    # L'URL retenue reste celle de l'oeuvre : ouvrir la fiche depuis une entree
    # d'historique ne doit pas atterrir sur une saison figee.
    assert res[0]["url"] == SITE_URL + "/catalogue/hell-mode/"


def test_historique_seul_est_ramene_a_l_oeuvre():
    data = {
        "logged_in": True,
        "history": {
            "nom": ["Hell Mode"],
            "url": ["/catalogue/hell-mode/saison2/vostfr/"],
            "img": [""],
        },
    }
    res = parse_favoris_api(data)
    assert len(res) == 1
    assert res[0]["url"] == SITE_URL + "/catalogue/hell-mode/"
    assert res[0]["listes"] == ["historique"]


def test_url_sans_barre_finale_ne_duplique_pas_l_oeuvre():
    data = {
        "logged_in": True,
        "favorites": {"nom": ["Slime"], "url": ["/catalogue/slime"], "img": [""]},
        "watchlist": {"nom": ["Slime"], "url": ["/catalogue/slime/"], "img": [""]},
    }
    res = parse_favoris_api(data)
    assert len(res) == 1
    assert res[0]["listes"] == ["favoris", "watchlist"]
    assert res[0]["url"] == SITE_URL + "/catalogue/slime"


def test_liste_vide_ou_absente_n_ajoute_rien():
    data = {
        "logged_in": True,
        "favorites": _liste("Solo"),
        "viewed": {"nom": [], "url": [], "img": []},
    }
    res = parse_favoris_api(data)
    assert [a["listes"] for a in res] == [["favoris"]]


def test_liste_malformee_ne_casse_pas_les_autres():
    data = {
        "logged_in": True,
        "favorites": _liste("Solo"),
        "watchlist": ["pas", "un", "dict"],
        "viewed": {"url": "pas une liste"},
    }
    assert [a["nom"] for a in parse_favoris_api(data)] == ["Solo"]


def test_url_hors_site_reste_rejetee_dans_toutes_les_listes():
    data = {
        "logged_in": True,
        "watchlist": {
            "nom": ["Piege"],
            "url": ["https://evil.example/catalogue/piege/"],
            "img": [""],
        },
    }
    assert parse_favoris_api(data) == []


