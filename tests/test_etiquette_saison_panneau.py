"""« ep.saison » est un index de panneau, pas un numero de saison.

Journal releve par l'utilisateur : « Dragon Ball Super S02E002 » ajoute a la
file devenait « Film E002 ». Les deux etiquettes decrivaient le meme episode,
mais l'une exposait l'index du panneau sur la fiche et l'autre son libelle reel.
Le disque, lui, suit le libelle. Ces tests verrouillent le fait que le libelle
fait foi partout ou l'episode est nomme.
"""

from pathlib import Path

from engine.scraping.episodes import _construire_episodes
from engine.scraping.parser import parse_panneaux
from engine.scraping.parser.naming import dossier_saison, nom_fichier

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "static" / "js"

# Forme reelle relevee sur la fiche : un <h2> de section, puis un
# panneauAnime("libelle", "chemin/langue") par onglet.
FICHE = """
<h2>Anime</h2>
<script>
panneauAnime("Saison 1", "saison1/vostfr");
panneauAnime("Film", "film/vostfr");
panneauAnime("Saison 2", "saison2/vostfr");
</script>
"""


def test_le_panneau_film_garde_son_libelle_et_son_index():
    panneaux = parse_panneaux(FICHE)

    assert [p["nom"] for p in panneaux] == ["Saison 1", "Film", "Saison 2"]
    assert [p["seg"] for p in panneaux] == ["saison1", "film", "saison2"]


def test_saison_porte_l_index_du_panneau_pas_un_numero_de_saison():
    infos = [
        (1, "Saison 1", "saison1", "vostfr", [1, 2]),
        (2, "Film", "film", "vostfr", [1]),
        (3, "Saison 2", "saison2", "vostfr", [1]),
    ]

    eps = _construire_episodes("dragon-ball-super", "Dragon Ball Super", infos)
    par_nom = {e["saison_nom"]: e for e in eps}

    # Le film est le deuxieme panneau : « saison » vaut 2 sans qu'aucune
    # saison 2 ne soit concernee.
    assert par_nom["Film"]["saison"] == 2
    assert par_nom["Saison 2"]["saison"] == 3


def test_le_dossier_et_le_fichier_suivent_le_libelle_pas_l_index():
    infos = [(2, "Film", "film", "vostfr", [2])]
    ep = _construire_episodes("dragon-ball-super", "Dragon Ball Super", infos)[0]

    dossier = dossier_saison(ep["saison_nom"], ep["saison"])
    fichier = nom_fichier(
        ep["titre"], ep["saison"], ep["episode"], ep["langue"], ep["saison_nom"]
    )

    assert dossier == "Film"
    assert "S02" not in fichier
    assert fichier == "Dragon Ball Super - Film - E002 VOSTFR"


def test_une_vraie_saison_reste_numerotee():
    infos = [(3, "Saison 2", "saison2", "vostfr", [6])]
    ep = _construire_episodes("skeleton-knight", "Skeleton Knight", infos)[0]

    assert dossier_saison(ep["saison_nom"], ep["saison"]) == "Saison 02"
    assert nom_fichier(
        ep["titre"], ep["saison"], ep["episode"], ep["langue"], ep["saison_nom"]
    ) == "Skeleton Knight - S02E006 VOSTFR"


def test_le_front_nomme_les_episodes_par_un_seul_chemin():
    partages = (JS / "utils" / "etiquette.js").read_text(encoding="utf-8")
    assert "saison_nom" in partages

    for page in ("home.js", "downloads.js"):
        src = (JS / "pages" / page).read_text(encoding="utf-8")
        assert "etiquetteEpisode" in src, page
        # Aucune reconstruction locale : c'est elle qui inventait « S08 ».
        assert "ep.saison" not in src, page
        assert "saison_nom" not in src, page


def test_la_fiche_groupe_les_saisons_par_le_meme_libelle():
    src = (JS / "pages" / "anime-modal.js").read_text(encoding="utf-8")

    assert "etiquetteSaison" in src
    assert "`Saison ${s}`" not in src
