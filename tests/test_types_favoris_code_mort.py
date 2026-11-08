"""Regression : le filtre Animes/Scans des favoris ne triait rien.

Toute fiche porte les definitions ``function panneauScan(nom, url)``, un
commentaire de documentation et un gabarit ``/*panneauScan("nom", "url")*/`` par
section ; certaines desactivent leur section Manga entiere par ``<!-- MANGA ... -->``
en laissant l'appel intact. Chercher ``"panneauScan("`` dans le HTML brut
classait 243 favoris sur 243 « both ». Fiches reconstituees d'apres le HTML
releve le 07/11/2026 (Hell Mode, One Piece).
"""

import json

from engine.scraping.parser.episodes import parse_panneaux
from engine.scraping.parser.profile import detecter_type_contenu

_COMMUN = """<script>
/* Fonctions appelees depuis l'index.php de chaque oeuvre :
   panneauAnime("nom", "saison1/vostfr"); panneauScan("nom", "scan/vf"); */
function _carte(nom, url, anime) { document.write('<a href="' + url + '"><span>' + nom + '</span></a>'); }
function panneauAnime(nom, url) { _carte(nom, url, true); }
function panneauScan(nom, url) { _carte(nom, url, false); }
</script>"""

_ANIME = """<h2 class="text-white">Anime</h2>
<div><script>
/*panneauAnime("nom", "url"); -> on en met autant qu'on veut a la ligne*/
panneauAnime("Saison 1", "saison1/vostfr");
panneauAnime("Saison 2", "saison2/vostfr");
</script></div>"""

_MANGA = """<h2 class="text-white">Manga</h2>
<div><script>
/*panneauScan("nom", "url"); -> on en met autant qu'on veut a la ligne*/
panneauScan("Scans", "scan/vf");
</script></div>"""


def _fiche(*sections: str) -> str:
    return "<html><body>" + _COMMUN + "".join(sections) + "</body></html>"


def _commente(section: str) -> str:
    return f"<!-- MANGA\n{section}\n-->"


def test_section_manga_en_commentaire_html_ne_fait_pas_un_scan():
    html = _fiche(_ANIME, _commente(_MANGA))
    assert detecter_type_contenu(html) == {"has_anime": True, "has_scan": False}


def test_section_anime_en_commentaire_html_laisse_un_scan_seul():
    html = _fiche(_commente(_ANIME), _MANGA)
    assert detecter_type_contenu(html) == {"has_anime": False, "has_scan": True}


def test_deux_sections_actives_restent_both():
    assert detecter_type_contenu(_fiche(_ANIME, _MANGA)) == {"has_anime": True, "has_scan": True}


def test_fiche_sans_aucun_panneau_actif_ne_retombe_pas_sur_les_liens():
    # Les gabarits et definitions disent que la fiche suit la mise en page a
    # panneaux : un lien egare vers une saison ne doit pas la classer anime.
    html = _fiche(_commente(_ANIME), _commente(_MANGA)) + '<a href="/catalogue/x/saison1/vostfr">x</a>'
    assert detecter_type_contenu(html) == {"has_anime": False, "has_scan": False}


def test_appel_commente_en_ligne_ignore():
    manga = _MANGA.replace('panneauScan("Scans"', '// panneauScan("Scans"')
    assert detecter_type_contenu(_fiche(_ANIME, manga)) == {"has_anime": True, "has_scan": False}


def test_ouverture_de_commentaire_html_dans_un_script_n_avale_rien():
    # Dans un <script>, « <!-- » n'ouvre pas de commentaire HTML : les panneaux
    # qui suivent restent executes par le navigateur.
    anime = _ANIME.replace("<script>", '<script>var marque = "<!--";')
    assert detecter_type_contenu(_fiche(anime, _MANGA)) == {"has_anime": True, "has_scan": True}


def test_parse_panneaux_ignore_aussi_les_sections_en_commentaire_html():
    # Jumeau du detecteur : la liste des saisons lit les memes appels.
    autre = _ANIME.replace("Anime", "Kai").replace("Saison 1", "Kai 1").replace("saison1/", "kai/")
    autre = autre.replace('panneauAnime("Saison 2", "saison2/vostfr");\n', "")
    panneaux = parse_panneaux(_fiche(_ANIME, _commente(autre), _commente(_MANGA)))
    assert [(p["nom"], p["seg"]) for p in panneaux] == [("Saison 1", "saison1"), ("Saison 2", "saison2")]


def test_cache_des_types_change_de_nom_et_retire_la_v5(tmp_path, monkeypatch):
    from engine.scraping import search

    perime = tmp_path / "scan_types_v5.json"
    perime.write_text(json.dumps({"https://x/catalogue/a/": "both"}), encoding="utf-8")
    monkeypatch.setattr(search, "_TYPES_FILE", tmp_path / search._TYPES_FILE.name)
    monkeypatch.setattr(search, "_types_cache", {})
    monkeypatch.setattr(search, "_types_loaded", False)

    search._load_types_cache()

    assert search._TYPES_FILE.name == "scan_types_v6.json"
    assert not perime.exists()
    assert search._types_cache == {}
