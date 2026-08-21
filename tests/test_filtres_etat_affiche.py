"""Une puce de filtre doit dire ce que la liste montre vraiment.

Trouves en relisant le correctif du point 6 : la barre de la recherche marquait
« Tous » actif en dur, alors qu'une session restauree replace _filtreActif. Les
resultats etaient filtres par langue sous une puce qui affichait le contraire.
Et les puces de langue de la librairie ne portaient aria-pressed qu'apres un
premier clic.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "static" / "js"

PAGES = {
    "search.js": "_filtreActif",
    "library.js": "_langueActif",
    "favorites.js": "_filtreActif",
}


def _src(nom: str) -> str:
    return (JS / "pages" / nom).read_text(encoding="utf-8")


_TERNAIRE_ACTIVE = re.compile(r"\?[^?]{0,40}?active")


def _puces_langue(nom: str) -> list[str]:
    return [
        l for l in _src(nom).splitlines()
        if "data-langue=" in l and "<button" in l
    ]


def test_aucune_puce_de_langue_n_est_active_en_dur():
    # Chaque « active » d'un gabarit de puce doit etre le bras d'un ternaire :
    # « class="fil-btn active" » ecrit en dur mentait des qu'une session
    # restauree replacait un filtre de langue.
    for nom in PAGES:
        for ligne in _puces_langue(nom):
            poses = ligne.count("active")
            conditionnes = len(_TERNAIRE_ACTIVE.findall(ligne))
            assert poses == conditionnes, f"{nom} : {ligne.strip()}"


def test_chaque_puce_de_langue_annonce_son_etat():
    for nom in PAGES:
        puces = _puces_langue(nom)
        assert puces, nom
        for ligne in puces:
            assert "aria-pressed=" in ligne, f"{nom} : {ligne.strip()}"


def test_l_etat_affiche_est_derive_de_la_variable_de_filtre():
    for nom, variable in PAGES.items():
        for ligne in _puces_langue(nom):
            assert variable in ligne, f"{nom} : {ligne.strip()}"


def test_le_bascule_partage_pose_toujours_les_deux_marques():
    src = (JS / "utils" / "filtres.js").read_text(encoding="utf-8")

    assert "classList.toggle('active'" in src
    assert "aria-pressed" in src


def test_les_quatre_barres_passent_par_le_meme_helper():
    for nom in ("library.js", "favorites.js", "search.js"):
        assert "basculerFiltre" in _src(nom), nom
