"""Ouverture d'une fiche : ce qui attend, et ce qui n'a pas a attendre.

loadAnimeModal enchainait deux allers-retours en serie — les reglages puis les
episodes — alors que la langue par defaut ne conditionne pas la requete. Et le
prechargement ne partait qu'apres 140 ms de survol : un clic rapide, une
tabulation ou un ecran tactile n'en profitaient jamais, faute de pointerover.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "static" / "js"
MODAL = JS / "pages" / "anime-modal.js"
PREFETCH = JS / "utils" / "prefetch.js"


def test_les_reglages_et_les_episodes_partent_ensemble():
    src = MODAL.read_text(encoding="utf-8")
    corps = src[src.index("export async function loadAnimeModal") : src.index("function renderAnimeModal")]

    assert "Promise.all" in corps

    i_reglages = corps.index("/api/settings")
    i_episodes = corps.index("getEpisodes")
    entre_les_deux = corps[min(i_reglages, i_episodes) : max(i_reglages, i_episodes)]
    assert "await" not in entre_les_deux, "les deux requetes sont encore en serie"


def test_un_echec_des_reglages_n_empeche_pas_la_grille():
    """Les reglages ne servent qu'a preselectionner une langue : leur panne ne
    doit pas priver l'utilisateur de la liste des episodes."""
    src = MODAL.read_text(encoding="utf-8")
    corps = src[src.index("export async function loadAnimeModal") : src.index("function renderAnimeModal")]

    assert "allSettled" in corps or "catch" in corps


def test_le_prechargement_part_des_le_pointerdown():
    src = PREFETCH.read_text(encoding="utf-8")

    assert "pointerdown" in src
    assert "pointerover" in src

    # pointerdown precede click : attendre un delai la reviendrait a ne rien
    # precharger du tout.
    debut = src.index("addEventListener('pointerdown'")
    bloc = src[debut : src.index("}, { passive: true })", debut)]
    assert "setTimeout" not in bloc, bloc


def test_le_module_de_la_fiche_est_precharge_lui_aussi():
    """La modale vit dans un chunk separe : sans ce prechargement, le premier
    clic paie l'aller-retour du chunk avant meme d'afficher le squelette."""
    src = PREFETCH.read_text(encoding="utf-8")

    assert "anime-modal.js" in src


def test_les_scans_sont_precharges_aussi():
    favoris = (JS / "pages" / "favorites.js").read_text(encoding="utf-8")

    assert "data-prefetch-scan" in favoris
    # L'ancien gabarit n'ecrivait data-prefetch que hors mode scan.
    assert "_typeActif !== 'scan' ? ` data-prefetch=" not in favoris

    cartes = re.findall(r'class="(?:anime-card|fav-list-item)"[^`]*?data-idx="\$\{i\}"([^\n]*)', favoris)
    assert cartes, "gabarits de carte introuvables"
    for attrs in cartes:
        assert "_attrPrefetch(a)" in attrs, attrs


def test_l_api_expose_un_prechargement_de_scan():
    api = (JS / "api.js").read_text(encoding="utf-8")

    assert "prefetchScan" in api
    # Sans mise en cache, precharger relancerait simplement la requete au clic.
    assert re.search(r"getScanInfo:.*getCached", api), "getScanInfo n'est pas mis en cache"


def test_la_vue_liste_de_la_recherche_precharge_comme_la_grille():
    src = (JS / "pages" / "search.js").read_text(encoding="utf-8")
    liste = src[src.index("anime-list-item") :]

    assert "data-prefetch" in liste.split("</div>`).join('')")[0]
