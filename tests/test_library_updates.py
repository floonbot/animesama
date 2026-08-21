from engine.library import scanner
from engine.library.updates import (
    ep_est_ignore,
    invalider_cache_updates,
    normaliser_nom,
)


def test_normaliser_nom_strips_accents_lang_season():
    assert normaliser_nom("Démon Slayer Saison 2 VOSTFR") == "demon slayer"

def test_normaliser_nom_empty():
    assert normaliser_nom("") == ""

def test_ep_est_ignore_saison():
    regle = {"saisons_ignorees": [2]}
    assert ep_est_ignore(regle, 2, 5) is True
    assert ep_est_ignore(regle, 1, 5) is False

def test_ep_est_ignore_episode():
    regle = {"episodes_ignores": {"1": [3, 4]}}
    assert ep_est_ignore(regle, 1, 3) is True
    assert ep_est_ignore(regle, 1, 9) is False

def test_ep_est_ignore_empty_rule():
    assert ep_est_ignore({}, 1, 1) is False

def test_library_cache_invalidation_wiring():
    scanner.librairie_cache_set({"animes": [], "total": 0})
    assert scanner.librairie_cache_get() is not None
    scanner.invalider_cache_librairie()
    assert scanner.librairie_cache_get() is None

def test_updates_cache_invalidation_wiring():
    import engine.library.updates as u
    u._updates_tc.set({"x": 1})
    assert u._updates_tc.get() is not None
    invalider_cache_updates()
    assert u._updates_tc.get() is None
