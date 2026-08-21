"""Deux dictionnaires globaux grossissaient sans plafond sur un process qui tourne
des heures : _host_throttle (purgé seulement quand on interroge l'hôte concerné) et
_echecs du cache négatif des covers (purge limitée aux entrées déjà expirées).
"""

import time

from engine.cache import cover_images
from engine.download import _rate_limiter as rl


def test_host_throttle_ne_grossit_pas_indefiniment(monkeypatch):
    monkeypatch.setattr(rl, "_host_throttle", {})
    for i in range(rl.HOST_THROTTLE_MAX * 3):
        rl.marquer_hote_throttle(f"h{i}.test")

    assert len(rl._host_throttle) <= rl.HOST_THROTTLE_MAX


def test_host_throttle_purge_les_entrees_expirees(monkeypatch):
    monkeypatch.setattr(rl, "_host_throttle", {"vieux.test": time.time() - 1})
    rl.marquer_hote_throttle("neuf.test")

    assert "vieux.test" not in rl._host_throttle
    assert rl.hote_throttle("neuf.test") is True


def test_host_throttle_garde_les_entrees_actives(monkeypatch):
    monkeypatch.setattr(rl, "_host_throttle", {})
    rl.marquer_hote_throttle("actif.test")
    for i in range(rl.HOST_THROTTLE_MAX * 2):
        rl.marquer_hote_throttle(f"bruit{i}.test")

    assert len(rl._host_throttle) <= rl.HOST_THROTTLE_MAX


def test_cache_negatif_covers_est_plafonne(monkeypatch):
    monkeypatch.setattr(cover_images, "_echecs", {})
    for i in range(cover_images.NEG_MAX * 2):
        cover_images._marquer_echec(f"https://cdn.test/{i}.jpg")

    assert len(cover_images._echecs) <= cover_images.NEG_MAX


def test_cache_negatif_covers_garde_les_plus_recents(monkeypatch):
    monkeypatch.setattr(cover_images, "_echecs", {})
    for i in range(cover_images.NEG_MAX + 10):
        cover_images._marquer_echec(f"https://cdn.test/{i}.jpg")

    dernier = f"https://cdn.test/{cover_images.NEG_MAX + 9}.jpg"
    assert cover_images._est_en_echec(dernier) is True
