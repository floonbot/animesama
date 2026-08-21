import asyncio

import engine.auth.manager as auth_mod
import engine.library.scanner as scanner_mod
import engine.library.updates as updates
import engine.scraping.scraper as scraper_mod


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


def test_panneau_film_avant_saison3_ne_saffiche_pas_comme_saison3(monkeypatch):
    updates.invalider_cache_updates()
    librairie = {
        "animes": [
            {
                "nom": "Tensei Shitara Slime Datta Ken",
                "saisons": [
                    {"nom": "Saison 03", "episodes": [
                        {"nom": "Tensei Shitara Slime Datta Ken - S03E001 VOSTFR"},
                        {"nom": "Tensei Shitara Slime Datta Ken - S03E025 VOSTFR"},
                    ]},
                ],
            }
        ]
    }
    favoris = [{"nom": "Tensei Shitara Slime Datta Ken", "url": "http://site/slime"}]
    episodes = {
        "http://site/slime": {
            "titre": "Tensei Shitara Slime Datta Ken",
            "episodes": [
                {"saison": 3, "episode": 1, "url": "film1", "langue": "VOSTFR", "saison_nom": "Film"},
                {"saison": 4, "episode": 1, "url": "s3e1", "langue": "VOSTFR", "saison_nom": "Saison 3"},
                {"saison": 4, "episode": 25, "url": "s3e25", "langue": "VOSTFR", "saison_nom": "Saison 3"},
            ],
        }
    }
    _patch(monkeypatch, librairie=librairie, favoris=favoris, episodes_by_url=episodes)

    out = asyncio.run(updates.check_updates_async())

    eps = out["animes"][0]["nouveaux_episodes"]
    assert {e["url"] for e in eps} == {"film1"}
    film = eps[0]
    assert film["saison_label"] == "Film"
    assert film["saison"] == 3

    from engine.scraping.parser import dossier_saison, nom_fichier

    dossier = dossier_saison(film["saison_nom"], film["saison"])
    nom = nom_fichier(
        film["titre"], film["saison"], film["episode"], film["langue"], film["saison_nom"]
    )
    assert dossier == "Film"
    assert nom == "Tensei Shitara Slime Datta Ken - Film - E001 VOSTFR"
    assert dossier != "Saison 03"
    assert "S03E001" not in nom


def test_saison_label_reflete_le_nom_reel_pas_l_index(monkeypatch):
    updates.invalider_cache_updates()
    librairie = {
        "animes": [
            {
                "nom": "Slime",
                "saisons": [
                    {"nom": "Saison 01", "episodes": [{"nom": "Slime - S01E001 VOSTFR"}]},
                ],
            }
        ]
    }
    favoris = [{"nom": "Slime", "url": "http://site/s"}]
    episodes = {
        "http://site/s": {
            "titre": "Slime",
            "episodes": [
                {"saison": 6, "episode": 1, "url": "oav1", "langue": "VOSTFR", "saison_nom": "OAV"},
                {"saison": 4, "episode": 1, "url": "s3e1", "langue": "VOSTFR", "saison_nom": "Saison 3"},
            ],
        }
    }
    _patch(monkeypatch, librairie=librairie, favoris=favoris, episodes_by_url=episodes)

    out = asyncio.run(updates.check_updates_async())

    eps = out["animes"][0]["nouveaux_episodes"]
    par_url = {e["url"]: e for e in eps}
    assert par_url["oav1"]["saison_label"] == "OAV"
    assert par_url["s3e1"]["saison_label"] == "Saison 03"
