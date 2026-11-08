"""Le commentaire de documentation de la fiche n'est pas un panneau.

Releve le 06/11/2026 sur anime-sama.to, apres la refonte de la page d'oeuvre :
chaque fiche embarque desormais, avant toute section, un commentaire qui
documente les fonctions de la page, exemple d'appel compris :

    /* ... panneauAnime("nom", "saison1/vostfr"); panneauScan("nom", "scan/vf"); */

parse_panneaux le lisait comme un vrai panneau. Venu en premier, il gagnait la
deduplication par chemin : la saison 1 s'appelait « nom ». Et comme il n'est
sous aucun <h2>, il creait une section fantome qui faisait prefixer toutes les
autres saisons de « Anime - ». Aucun dossier local ne portant ces noms, la
librairie annoncait 1557 episodes « nouveaux » sur 48 animes deja telecharges,
et un telechargement lance depuis la fiche les aurait ranges dans un dossier
« nom », a cote des fichiers existants qu'il ne voyait pas.

Les extraits ci-dessous reproduisent la forme de la page, pas son contenu.
"""

from engine.cache.disk_cache import DiskCache
from engine.scraping import episodes as ep_mod
from engine.scraping.parser import parse_panneaux
from engine.scraping.parser.naming import dossier_saison, nom_fichier

FICHE_REFONDUE = """
<script>
/* Documentation des cartes de la page :
   panneauAnime("nom", "saison1/vostfr"); panneauScan("nom", "scan/vf"); */
function panneauAnime(nom, url) { carte(nom, url, false); }
function panneauScan(nom, url) { carte(nom, url, true); }
</script>
<h2 class="oe-h2">Synopsis</h2>
<h2>Anime</h2>
<script>
/*panneauAnime("nom", "url"); -> un appel par ligne*/
panneauAnime("Saison 1", "saison1/vostfr");
panneauAnime("Saison 2", "saison2/vostfr");
panneauAnime("Film", "film/vostfr");
</script>
<h2>Manga</h2>
<script>
/*panneauScan("nom", "url"); -> un appel par ligne*/
panneauScan("Scans", "scan/vf");
</script>
"""


def test_le_commentaire_de_documentation_n_est_pas_un_panneau():
    assert parse_panneaux(FICHE_REFONDUE) == [
        {"nom": "Saison 1", "seg": "saison1", "lang": "vostfr"},
        {"nom": "Saison 2", "seg": "saison2", "lang": "vostfr"},
        {"nom": "Film", "seg": "film", "lang": "vostfr"},
    ]


def test_les_fichiers_retrouvent_les_dossiers_deja_sur_le_disque():
    # C'est ce nom-la que suivent le telechargement et la detection des
    # nouveautes : il doit retomber sur « Saison 01 », pas sur « nom ».
    noms = [p["nom"] for p in parse_panneaux(FICHE_REFONDUE)]

    assert [dossier_saison(n, i) for i, n in enumerate(noms, 1)] == [
        "Saison 01", "Saison 02", "Film",
    ]
    assert nom_fichier("Beelzebub", 1, 1, "VOSTFR", noms[0]) == "Beelzebub - S01E001 VOSTFR"


def test_le_gabarit_nom_est_ignore_meme_hors_commentaire():
    # Filet si le site sort un jour l'exemple de son commentaire : un vrai
    # panneau ne s'appelle jamais « nom », et celui-ci volerait le chemin
    # de la saison 1 a la deduplication.
    html = (
        "<h2>Anime</h2><script>"
        'panneauAnime("nom", "saison1/vostfr");'
        'panneauAnime("Saison 1", "saison1/vostfr");'
        "</script>"
    )

    assert parse_panneaux(html) == [{"nom": "Saison 1", "seg": "saison1", "lang": "vostfr"}]


def test_un_faux_debut_de_commentaire_n_avale_pas_les_panneaux_d_un_autre_script():
    # « image/* » ouvre un commentaire pour une recherche naive sur toute la
    # page, et « */ » le referme deux scripts plus loin. Le nettoyage se fait
    # script par script : chacun ne peut perdre que son propre contenu.
    html = (
        '<script>var accepte = "image/*";</script>'
        "<h2>Anime</h2>"
        '<script>panneauAnime("Saison 1", "saison1/vostfr");</script>'
        '<script>var fin = "*/";</script>'
    )

    assert parse_panneaux(html) == [{"nom": "Saison 1", "seg": "saison1", "lang": "vostfr"}]


def test_le_cache_disque_ecrit_par_l_ancien_parseur_n_est_pas_resservi():
    # Le cache des episodes survit une heure au redemarrage. Sans version, la
    # mise a jour resservait les saisons « nom » calculees par l'ancien binaire,
    # qui les ecrivait sous l'URL nue.
    url = "https://anime-sama.to/catalogue/cache-ancien-parseur"
    ancien = DiskCache("episodes", 3600)
    try:
        ancien.set(url, {"titre": "X", "episodes": [{"saison_nom": "nom"}]})

        assert ep_mod._ep_disk.get(url) is None
    finally:
        ancien.delete(url)
        ancien.close()


def test_deux_versions_d_un_meme_cache_ne_se_voient_pas(tmp_path, monkeypatch):
    from engine.cache import disk_cache

    monkeypatch.setattr(disk_cache, "DATA_DIR", tmp_path)
    v1 = DiskCache("essai", 3600, version="1")
    v2 = DiskCache("essai", 3600, version="2")
    try:
        v1.set("cle", {"v": 1})
        v2.set("cle", {"v": 2})

        assert v1.get("cle") == {"v": 1}
        assert v2.get("cle") == {"v": 2}

        v2.delete("cle")
        assert v2.get("cle") is None
        assert v1.get("cle") == {"v": 1}
    finally:
        v1.close()
        v2.close()
