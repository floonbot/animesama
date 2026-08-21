"""L'interface se met a jour seule.

Le mecanisme existait mais n'etait branche que sur le diagnostic : events.js
republiait deja sse-activity, router.js emet page-changed, et diag.js s'arrete
hors de la vue. Ailleurs, _invalidateLib() ne faisait que vider le cache HTTP —
aucun rendu — et loadLibrairie sortait d'office pendant 30 s, si bien qu'un
telechargement termine ne changeait rien a l'ecran, meme en revenant sur la page.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "static" / "js"
VUE_LIVE = JS / "utils" / "vue-live.js"
EVENTS = JS / "events.js"
LIB = JS / "pages" / "library.js"
FAV = JS / "pages" / "favorites.js"
HOME = JS / "pages" / "home.js"


def test_le_helper_de_vue_vivante_existe():
    assert VUE_LIVE.is_file()


def test_il_suit_le_patron_de_diag():
    """diag.js s'arrete hors de la vue : le reste de l'app doit en faire autant,
    sinon « toujours a jour » devient « toujours en train de recalculer »."""
    src = VUE_LIVE.read_text(encoding="utf-8")

    assert "page-changed" in src
    assert "visibilitychange" in src
    assert "data-changed" in src
    assert "document.hidden" in src


def test_aucun_sondage_periodique_n_est_introduit():
    """Une information qui n'arrive pas doit passer par le SSE, pas par une
    boucle d'interrogation."""
    src = VUE_LIVE.read_text(encoding="utf-8")

    assert "setInterval" not in src


def test_events_publie_un_changement_et_pas_seulement_une_invalidation():
    src = EVENTS.read_text(encoding="utf-8")

    assert "signalerChangement" in src
    bloc = src[src.index("function _invalidateLib") : src.index("let es ")]
    assert "signalerChangement" in bloc, "_invalidateLib ne vide toujours que le cache"


@pytest.mark.parametrize("page", ["library.js", "favorites.js", "home.js"])
def test_les_pages_s_abonnent(page):
    src = (JS / "pages" / page).read_text(encoding="utf-8")

    assert "vue-live.js" in src
    assert "abonnerVue" in src


def test_l_invalidation_court_circuite_la_garde_de_fraicheur():
    """Les 30 s protegent des rafales, pas de la verite : une invalidation
    explicite doit passer devant."""
    src = LIB.read_text(encoding="utf-8")

    garde = src[src.index("export async function loadLibrairie") :]
    garde = garde[: garde.index("_renderSkeleton")]
    assert "30000" in garde
    assert re.search(r"_libSale|sale", garde), "la garde ignore encore l'invalidation"


def test_un_rafraichissement_vivant_ne_vide_pas_la_recherche_en_cours():
    """Reconstruire la barre d'outils remettait le champ a vide et les boutons
    sur leurs valeurs par defaut : « toujours a jour » effacait la frappe."""
    src = LIB.read_text(encoding="utf-8")

    barre = src[src.index('id="lib-search"') - 400 : src.index('id="lib-expand-all"')]
    assert "_recherche" in barre, "le champ de recherche ne rejoue pas l'etat courant"
    assert "_langueActif ===" in barre
    assert "_typeActif ===" in barre

    # Les puces de tri sont passees par un generateur le jour ou les six boutons
    # sont devenus cinq bascules : l'etat courant s'y rejoue, plus dans le
    # gabarit. La garantie est la meme, l'endroit a change.
    assert "_rendreBoutonsTri()" in barre, "les boutons de tri ne sont plus rejoues"
    gen = src[src.index("function _rendreBoutonsTri") :]
    gen = gen[: gen.index("\nfunction ")]
    assert "_sortActif" in gen, "le generateur des puces ignore le tri courant"


def test_les_favoris_non_plus_ne_perdent_pas_leur_recherche():
    """_renderToolbar reconstruit #fav-toolbar de zero : le champ repartait a
    vide, exactement comme celui de la librairie."""
    src = FAV.read_text(encoding="utf-8")

    barre = src[src.index('id="fav-search"') - 200 : src.index('id="fav-search-clear"') + 200]
    assert "_recherche" in barre
    assert 'value=""' not in barre

    # Le filtrage lit l'etat du module, pas le DOM : il doit rester juste meme
    # appele avant que la barre ne soit posee.
    rendu = src[src.index("function _renderCards") :]
    rendu = rendu[: rendu.index("function _scheduleChunk")]
    assert "jetonsRequete(_recherche)" in rendu


def test_le_squelette_ne_clignote_pas_sur_un_rafraichissement():
    src = LIB.read_text(encoding="utf-8")

    debut = src.index("_renderSkeleton(el)")
    ligne = src[src.rindex("\n", 0, debut) : debut + 40]
    assert "if" in ligne, "le squelette est repose meme quand la liste est deja la"


def test_supprimer_un_episode_previent_les_autres_vues():
    """La ligne disparaissait du DOM mais la librairie restait en cache : les
    favoris continuaient d'afficher « deja telecharge »."""
    src = LIB.read_text(encoding="utf-8")

    assert "signalerChangement" in src
    aide = src[src.index("function _signalerSuppression") :]
    aide = aide[: aide.index("\n}")]
    assert "invalidateCache('/api/anime/librairie')" in aide
    assert "signalerChangement" in aide

    for depart, fin in (
        ("if (action === 'delete')", "document.removeEventListener"),
        ("if (action === 'bulk-delete')", "if (action === 'bulk-cancel')"),
    ):
        bloc = src[src.index(depart) : src.index(fin)]
        assert "_signalerSuppression()" in bloc, depart


def test_changer_les_reglages_previent_les_vues_deja_rendues():
    # Le cablage a quitte app.js pour pages/settings.js quand Parametres est
    # devenu une page routee (C13.a) ; le signal, lui, reste obligatoire.
    src = (JS / "pages" / "settings.js").read_text(encoding="utf-8")

    bloc = src[src.index("async function _sauvegarder") :]
    assert "invalidateCache('/api/anime/librairie')" in bloc
    assert "signalerChangement(SUJET_REGLAGES)" in bloc


def test_le_son_de_notification_n_est_plus_fige_au_chargement():
    """_settingsCache etait lu une fois a l'import du module : decocher « son de
    notification » n'avait aucun effet avant rechargement complet."""
    src = (JS / "pages" / "downloads.js").read_text(encoding="utf-8")

    assert "data-changed" in src or "abonnerVue" in src


def test_le_badge_des_nouveautes_se_recalcule_sans_reinterroger_le_site():
    """check-updates scrape le site pour chaque anime, et le serveur invalide son
    cache a chaque episode reussi : le rejouer sur chaque rafraichissement
    vivant lancerait une rafale de requetes distantes. On rejoue ce qu'on sait,
    et l'age dit depuis quand."""
    src = LIB.read_text(encoding="utf-8")

    queue = src[src.index("try { applySortAndFilter(); } catch {}") :]
    queue = queue[: queue.index("});")]

    assert "majStatNouveaux()" in queue
    assert "checkNouveauxEpisodes(" in queue
    assert "vivant" in queue, "le rafraichissement vivant relance le scraping distant"


def test_l_age_de_la_derniere_verification_est_visible_pas_seulement_en_infobulle():
    """check-updates coute cher et sa reponse vient d'un cache de 5 min : un
    chiffre sans age se lit comme « a l'instant »."""
    src = (JS / "pages" / "library" / "updates.js").read_text(encoding="utf-8")

    assert "ageVerification" in src
    bloc = src[src.index("function _poserFraicheur") : src.index("export async function checkNouveauxEpisodes")]
    assert "textContent" in bloc or "lib-stat-age" in bloc, (
        "l'age n'est encore accessible qu'au survol"
    )
