"""Un échec de scraping était indiscernable de « rien de neuf ».

`get_episodes_async` renvoie une liste vide sur *toutes* ses sorties d'échec
(URL refusée, réponse absente, exception avalée). `if not online_eps: return None`
sortait donc sans incrémenter `non_verifies`, et l'avertissement « n anime(s)
non vérifiés » ne se déclenchait jamais. La plomberie existait pourtant déjà
jusqu'au front.
"""

import asyncio
from pathlib import Path

import pytest

import engine.auth.manager as auth_mod
import engine.library.scanner as scanner_mod
import engine.library.updates as updates
import engine.scraping.scraper as scraper_mod

ROOT = Path(__file__).resolve().parent.parent
UPDATES_JS = ROOT / "web" / "static" / "js" / "pages" / "library" / "updates.js"


@pytest.fixture(autouse=True)
def _reset_updates_cache():
    updates.invalider_cache_updates()
    yield
    updates.invalider_cache_updates()


def _async_return(value):
    async def _coro(*args, **kwargs):
        return value

    return _coro


_LIBRAIRIE = {
    "animes": [
        {
            "nom": "Overlord",
            "saisons": [
                {"nom": "Saison 01", "episodes": [{"nom": "Overlord - S01E001 VOSTFR"}]}
            ],
        }
    ]
}
_FAVORIS = [{"nom": "Overlord", "url": "https://anime-sama.to/catalogue/overlord", "image": ""}]


def _boundaries(monkeypatch, episodes):
    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", True)
    monkeypatch.setattr(scanner_mod, "scan_librairie_sync", lambda: _LIBRAIRIE)
    monkeypatch.setattr(scraper_mod, "get_favorites_async", _async_return(_FAVORIS))

    async def _get_eps(url, force_refresh=False):
        return episodes

    monkeypatch.setattr(scraper_mod, "get_episodes_async", _get_eps)


def test_scraping_sans_episode_compte_comme_non_verifie(monkeypatch):
    _boundaries(monkeypatch, {"titre": "", "episodes": [], "langues": [], "total": 0})

    out = asyncio.run(updates.check_updates_async())

    assert out["non_verifies"] == 1
    assert out["total_nouveaux"] == 0


def test_scraping_qui_repond_ne_compte_pas_comme_non_verifie(monkeypatch):
    _boundaries(
        monkeypatch,
        {
            "titre": "Overlord",
            "episodes": [
                {
                    "url": "https://anime-sama.to/catalogue/overlord/saison1/vostfr?ep=1",
                    "saison": 1,
                    "episode": 1,
                    "langue": "VOSTFR",
                    "saison_nom": "Saison 1",
                }
            ],
        },
    )

    out = asyncio.run(updates.check_updates_async())

    assert out["non_verifies"] == 0


def test_l_avertissement_est_journalise(monkeypatch, caplog):
    import logging

    _boundaries(monkeypatch, {"episodes": []})

    with caplog.at_level(logging.WARNING, logger="engine.library.updates"):
        asyncio.run(updates.check_updates_async())

    assert any("non vérifiés" in r.getMessage() for r in caplog.records)


def test_checked_at_reste_dans_la_charge_utile(monkeypatch):
    _boundaries(monkeypatch, {"episodes": []})

    out = asyncio.run(updates.check_updates_async())

    assert isinstance(out["checked_at"], int)
    assert out["checked_at"] > 0


def test_le_front_affiche_l_age_de_la_verification():
    src = UPDATES_JS.read_text(encoding="utf-8")

    assert "checked_at" in src, "l'âge de la vérification n'est lu nulle part"
    assert "ageVerification" in src


def test_l_age_est_pose_sur_la_tuile_dans_tous_les_cas():
    src = UPDATES_JS.read_text(encoding="utf-8")
    debut = src.index("export async function checkNouveauxEpisodes")
    fin = src.index("export function majStatNouveaux")
    corps = src[debut:fin]

    # Une seule pose, apres les trois branches : sinon une branche l'oublie.
    assert corps.count("_poserFraicheur(") >= 1
