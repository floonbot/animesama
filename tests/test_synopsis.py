"""Synopsis des fiches de la librairie et des favoris.

Balisage releve le 07/11/2026 sur la fiche refondue :
<p id="synopsisText" class="oe-replie">...</p>.
"""

import asyncio

import pytest

from engine.scraping import synopsis as syn
from engine.scraping.parser import parse_synopsis

_FICHE = """<h2 class="oe-h2">Synopsis</h2>
<div class="oe-synopsis">
  <p id="synopsisText" class="oe-replie">Un gamer choisit la difficult&eacute; maximale<br>
     et se <b>r&eacute;incarne</b>   ailleurs.</p>
  <button type="button" class="oe-voir-plus" data-cible="synopsisText" hidden>Voir plus</button>
</div>"""


def test_parse_synopsis_nettoie_balises_entites_et_espaces():
    assert parse_synopsis(_FICHE) == "Un gamer choisit la difficulté maximale\net se réincarne ailleurs."


def test_parse_synopsis_absent_ou_vide():
    assert parse_synopsis("") == ""
    assert parse_synopsis("<p class='oe-replie'>autre</p>") == ""


class _Rep:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def cache_vide(tmp_path, monkeypatch):
    from engine.cache.disk_cache import DiskCache

    monkeypatch.setattr(syn, "_disk", DiskCache(f"synopsis_test_{tmp_path.name}", 3600))
    monkeypatch.setattr(syn, "_url_par_nom", {})
    appels = []

    async def _get(url, cookies=None):
        appels.append(url)
        return reponses.pop(0) if reponses else None

    reponses: list = []
    monkeypatch.setattr(syn, "http_get", _get)
    return appels, reponses


def test_synopsis_mis_en_cache_y_compris_vide(cache_vide):
    appels, reponses = cache_vide
    reponses += [_Rep(_FICHE), _Rep("<html>sans synopsis</html>")]
    url = "https://anime-sama.to/catalogue/hell-mode/saison1/vostfr?ep=2"

    assert asyncio.run(syn.get_synopsis_async(url)).startswith("Un gamer")
    assert asyncio.run(syn.get_synopsis_async("https://anime-sama.to/catalogue/hell-mode/")).startswith("Un gamer")
    assert appels == ["https://anime-sama.to/catalogue/hell-mode"]  # une seule requete, par la fiche

    assert asyncio.run(syn.get_synopsis_async("https://anime-sama.to/catalogue/autre")) == ""
    assert asyncio.run(syn.get_synopsis_async("https://anime-sama.to/catalogue/autre")) == ""
    assert len(appels) == 2  # « pas de synopsis » retenu aussi


def test_echec_reseau_non_retenu(cache_vide):
    appels, reponses = cache_vide
    assert asyncio.run(syn.get_synopsis_async("https://anime-sama.to/catalogue/x")) == ""
    reponses.append(_Rep(_FICHE))
    assert asyncio.run(syn.get_synopsis_async("https://anime-sama.to/catalogue/x")).startswith("Un gamer")
    assert len(appels) == 2


def test_url_hors_site_refusee(cache_vide):
    appels, _ = cache_vide
    assert asyncio.run(syn.get_synopsis_async("https://ailleurs.example/catalogue/x")) == ""
    assert asyncio.run(syn.get_synopsis_async("pas une url")) == ""
    assert appels == []


def _brancher(monkeypatch, favoris, recherche):
    vus = []

    async def _fav():
        return favoris

    async def _search(q, known_covers=None):
        vus.append(q)
        return recherche

    monkeypatch.setattr("engine.scraping.favorites.get_favorites_async", _fav)
    monkeypatch.setattr("engine.scraping.search.search_async", _search)
    return vus


def test_nom_de_dossier_retrouve_dans_les_favoris(cache_vide, monkeypatch):
    vus = _brancher(monkeypatch, [{"nom": "Re:Zero", "url": "https://anime-sama.to/catalogue/re-zero/"}], [])
    # Le dossier « Re_Zero » et le titre « Re:Zero » se normalisent pareil.
    assert asyncio.run(syn.url_pour_nom("Re_Zero")) == "https://anime-sama.to/catalogue/re-zero/"
    assert vus == []  # pas de recherche sur le site


def test_recherche_seulement_sur_nom_identique(cache_vide, monkeypatch):
    vus = _brancher(monkeypatch, [], [
        {"nom": "Dr. Stone: New World", "url": "https://anime-sama.to/catalogue/dr-stone-nw"},
        {"nom": "Dr Stone", "url": "https://anime-sama.to/catalogue/dr-stone"},
    ])
    assert asyncio.run(syn.url_pour_nom("Dr Stone")) == "https://anime-sama.to/catalogue/dr-stone"
    assert asyncio.run(syn.url_pour_nom("Dr Stone")) == "https://anime-sama.to/catalogue/dr-stone"
    assert vus == ["Dr Stone"]  # memorise pour la session


def test_aucun_resultat_approchant_ne_sert_de_synopsis(cache_vide, monkeypatch):
    _brancher(monkeypatch, [], [{"nom": "Dr Stone Science Future", "url": "https://anime-sama.to/catalogue/x"}])
    assert asyncio.run(syn.url_pour_nom("Dr Stone")) == ""


def test_route_synopsis(client, monkeypatch):
    async def _syn(url):
        return f"texte de {url}"

    async def _nom(nom):
        return "https://anime-sama.to/catalogue/dr-stone" if nom == "Dr Stone" else ""

    monkeypatch.setattr(syn, "get_synopsis_async", _syn)
    monkeypatch.setattr(syn, "url_pour_nom", _nom)

    assert client.get("/api/anime/synopsis").status_code == 400
    assert client.get("/api/anime/synopsis?url=https://ailleurs.example/x").status_code == 400
    r = client.get("/api/anime/synopsis?nom=Dr%20Stone").json()
    assert r == {"synopsis": "texte de https://anime-sama.to/catalogue/dr-stone",
                 "url": "https://anime-sama.to/catalogue/dr-stone"}
    assert client.get("/api/anime/synopsis?nom=Inconnu").json() == {"synopsis": "", "url": ""}
