"""D3 — la matrice « evenement -> caches a invalider », rendue executable.

Douze fonctions d'invalidation existent, sans orchestrateur : chaque appelant
doit se souvenir du bon sous-ensemble. Ce fichier est la reference. Il encode la
chaine de dependances, mesuree en phase 0 :

    _CachedDir(5 s) -> dossiers(120 s) -> librairie(180 s) -> updates(300 s)
                                     favoris(300 s) ----------^

`check_updates_async` appelle `scan_librairie_sync()` en direct (pas le cache
librairie) et `get_favorites_async()` : son resultat derive donc des deux. Tout
evenement qui invalide un maillon doit invalider son aval, sans quoi le
diagnostic sert une valeur calculee sur l'etat d'avant.

Ce qui n'est PAS invalide compte autant : « episode terminé » ne touche pas au
cache dossiers, parce qu'un fichier de plus ne change pas la liste des racines.
"""

import asyncio

import pytest

import engine.config.logging_setup  # noqa: F401  (installe log.success)
import engine.config.settings as cfg
from engine.library import scanner, updates
from engine.scraping._cache import cache as scrap_cache

WRITE = {"origin": "http://localhost:7843"}


def _amorcer_tous_les_caches(tmp_path):
    """Remplit chaque cache d'un marqueur reconnaissable."""
    scanner._dossiers_cache.set([tmp_path])
    scanner.librairie_cache_set({"animes": [], "marqueur": "avant"})
    updates._updates_tc.set({"animes": [], "marqueur": "avant"})
    scrap_cache.set_fav([{"nom": "Avant"}])


def _etat() -> dict[str, bool]:
    """True = le cache est encore chaud."""
    return {
        "dossiers": scanner._dossiers_cache.get() is not None,
        "librairie": scanner.librairie_cache_get() is not None,
        "updates": updates._updates_tc.get() is not None,
        "favoris": scrap_cache.fav_fresh(),
    }


@pytest.fixture(autouse=True)
def _caches_propres():
    yield
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    updates.invalider_cache_updates()
    scrap_cache.invalidate_fav()
    cfg.invalider_downloads_dir_cache()
    cfg.invalider_scans_dir_cache()


# --------------------------------------------------------------------------
# 1. Episode terminé  ->  librairie + updates,  PAS dossiers
# --------------------------------------------------------------------------
def test_episode_termine_invalide_librairie_et_updates(tmp_path):
    import web.api.routes.sse as sse_mod

    _amorcer_tous_les_caches(tmp_path)
    sse_mod._refresh_library_on_success("episode_done", {"succes": True, "skipped": False})

    assert _etat() == {
        "dossiers": True,      # un fichier de plus ne change pas les racines
        "librairie": False,
        "updates": False,
        "favoris": True,       # rien a voir avec le compte
    }


def test_episode_ignore_ou_echoue_n_invalide_rien(tmp_path):
    import web.api.routes.sse as sse_mod

    _amorcer_tous_les_caches(tmp_path)
    sse_mod._refresh_library_on_success("episode_done", {"succes": True, "skipped": True})
    sse_mod._refresh_library_on_success("episode_done", {"succes": False, "skipped": False})

    assert all(_etat().values())


def test_anime_termine_avec_au_moins_un_succes_invalide(tmp_path):
    import web.api.routes.sse as sse_mod

    _amorcer_tous_les_caches(tmp_path)
    sse_mod._refresh_library_on_success("anime_done", {"succes": 2, "skipped": 1, "echoues": 0})

    etat = _etat()
    assert etat["librairie"] is False
    assert etat["updates"] is False


# --------------------------------------------------------------------------
# 2. Episode supprimé  ->  librairie + updates
# --------------------------------------------------------------------------
def test_episode_supprime_invalide_librairie_et_updates(tmp_path, client, monkeypatch):
    fichier = tmp_path / "Un Anime" / "Saison 01" / "E01.mp4"
    fichier.parent.mkdir(parents=True)
    fichier.write_bytes(b"x" * 32)

    monkeypatch.setattr(scanner, "est_dans_downloads", lambda f: True)
    _amorcer_tous_les_caches(tmp_path)

    r = client.post("/api/anime/supprimer", json={"fichier": str(fichier)}, headers=WRITE)

    assert r.json()["ok"] is True
    etat = _etat()
    assert etat["librairie"] is False
    assert etat["updates"] is False


# --------------------------------------------------------------------------
# 3. Dossier de téléchargement changé  ->  dossiers + librairie + updates
# --------------------------------------------------------------------------
def test_changer_le_dossier_invalide_jusqu_a_updates(tmp_path, client, monkeypatch):
    """La cellule qui manquait : check_updates_async rescanne la librairie a
    chaque appel non cache, mais son propre cache de 300 s masquait le
    changement de dossier."""
    import engine.config.user_settings as us

    reglages = {"downloads_dir": ""}
    monkeypatch.setattr(us, "load_settings", lambda: dict(reglages))
    monkeypatch.setattr(us, "save_settings", lambda s: reglages.update(s) or True)
    import web.api.routes.settings as st_mod
    monkeypatch.setattr(st_mod, "load_settings", lambda: dict(reglages))
    monkeypatch.setattr(st_mod, "save_settings", lambda s: reglages.update(s) or True)

    nouveau = tmp_path / "nouveau_dossier"
    nouveau.mkdir()
    _amorcer_tous_les_caches(tmp_path)

    r = client.post("/api/settings", json={"downloads_dir": str(nouveau)}, headers=WRITE)
    assert r.json().get("ok") is not False, r.json()

    assert _etat() == {
        "dossiers": False,
        "librairie": False,
        "updates": False,
        "favoris": True,       # le compte n'a pas change
    }


# --------------------------------------------------------------------------
# 4. Connexion / déconnexion  ->  favoris + updates
# --------------------------------------------------------------------------
def test_connexion_invalide_favoris_et_updates(tmp_path, monkeypatch):
    """Les favoris et les nouveautes appartiennent au compte : les garder au
    chaud servait la liste du compte precedent pendant 300 s."""
    from engine.auth.manager import auth_manager

    _amorcer_tous_les_caches(tmp_path)
    monkeypatch.setattr(
        auth_manager, "_login_requests",
        lambda p, w: {"ok": True, "cookies": [{"name": "s", "value": "1"}]},
    )
    monkeypatch.setattr(auth_manager.storage, "save_credentials", lambda *a: None)
    monkeypatch.setattr(auth_manager.storage, "save_cookies", lambda *a: None)
    monkeypatch.setattr(auth_manager, "start_keepalive_loop", lambda: None)

    asyncio.run(auth_manager.login_async("flo", "pw"))

    etat = _etat()
    assert etat["favoris"] is False
    assert etat["updates"] is False
    assert etat["librairie"] is True   # les fichiers locaux n'ont pas bouge


def test_deconnexion_invalide_favoris_et_updates(tmp_path, monkeypatch):
    from engine.auth.manager import auth_manager

    _amorcer_tous_les_caches(tmp_path)
    monkeypatch.setattr(auth_manager, "stop_keepalive_loop", lambda: None)
    monkeypatch.setattr(auth_manager.storage, "clear_all", lambda: None)

    auth_manager.logout()

    etat = _etat()
    assert etat["favoris"] is False
    assert etat["updates"] is False
    assert etat["librairie"] is True
