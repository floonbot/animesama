import asyncio

import pytest

import engine.auth.manager as auth_mod
import engine.library.scanner as scanner_mod
import engine.library.updates as updates
import engine.scraping.scraper as scraper_mod
from engine.scraping.parser import nettoyer_titre, nom_fichier
from engine.utils.security import sanitize_filename

TITRE_TRAPPED = "Trapped in a Dating Sim: The World of Otome Games is Tough for Mobs"
TITRE_REZERO = "Re:Zero"


def _dossier_ecrit_sur_disque(titre: str) -> str:
    return nettoyer_titre(sanitize_filename(titre))


def _async_return(value):
    async def _coro(*args, **kwargs):
        return value

    return _coro


def _patch(monkeypatch, *, librairie, favoris, episodes_by_url):
    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", True)
    monkeypatch.setattr(scanner_mod, "scan_librairie_sync", lambda: librairie)
    monkeypatch.setattr(scraper_mod, "get_favorites_async", _async_return(favoris))

    async def _get_eps(url, force_refresh=False):
        return episodes_by_url.get(url, {"episodes": []})

    monkeypatch.setattr(scraper_mod, "get_episodes_async", _get_eps)


@pytest.mark.parametrize("titre", [TITRE_TRAPPED, TITRE_REZERO])
def test_normaliser_nom_apparie_le_dossier_ecrit_par_l_app_et_son_favori(titre):
    dossier = _dossier_ecrit_sur_disque(titre)

    assert updates.normaliser_nom(dossier) == updates.normaliser_nom(titre)


def test_check_updates_signale_les_episodes_manquants_d_un_titre_a_caractere_interdit(monkeypatch):
    updates.invalider_cache_updates()
    url = "http://site/trapped"
    dossier = _dossier_ecrit_sur_disque(TITRE_TRAPPED)
    librairie = {
        "animes": [
            {
                "nom": dossier,
                "saisons": [
                    {
                        "nom": "Saison 01",
                        "episodes": [
                            {"nom": nom_fichier(dossier, 1, i, "VOSTFR", "Saison 1")}
                            for i in range(1, 13)
                        ],
                    },
                    {
                        "nom": "Saison 02",
                        "episodes": [
                            {"nom": nom_fichier(dossier, 2, 1, "VOSTFR", "Saison 2")}
                        ],
                    },
                ],
            }
        ]
    }
    favoris = [{"nom": TITRE_TRAPPED, "url": url, "image": ""}]
    episodes = {
        url: {
            "titre": TITRE_TRAPPED,
            "episodes": [
                {
                    "url": f"{url}/s2e{i}",
                    "saison": 2,
                    "episode": i,
                    "langue": "VOSTFR",
                    "saison_nom": "Saison 2",
                }
                for i in range(1, 5)
            ],
        }
    }
    _patch(monkeypatch, librairie=librairie, favoris=favoris, episodes_by_url=episodes)

    out = asyncio.run(updates.check_updates_async(refresh=True))

    assert out["total_nouveaux"] == 3
    assert [
        (e["saison_label"], e["episode"], e["type"])
        for e in out["animes"][0]["nouveaux_episodes"]
    ] == [("Saison 02", 2, "nouveau"), ("Saison 02", 3, "nouveau"), ("Saison 02", 4, "nouveau")]
