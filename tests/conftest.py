import os
import sys
import tempfile
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# A executer AVANT le premier import de engine.* — d'ou la place en tete de
# fichier et le noqa: E402 sur les imports qui suivent.
#
# La suite ecrivait dans les donnees reelles de l'utilisateur : un run consommait
# une rotation de data/logs/app.log (backupCount=3, donc trois runs effacaient
# tout l'historique), et laissait grossir data/cache/episodes.db-wal. La cause
# n'est pas un test fautif en particulier : DATA_DIR etait fige a l'import, si
# bien qu'aucun monkeypatch ne pouvait l'atteindre partout.
_RACINE_DEPOT = Path(__file__).resolve().parent.parent

_data_tests = Path(tempfile.mkdtemp(prefix="animesama-tests-data-"))
os.environ["ANIMESAMA_DATA_DIR"] = str(_data_tests)
# Sans quoi tout test important `server` reinstalle un RotatingFileHandler sur
# le vrai journal — le defaut d'origine.
os.environ.setdefault("ANIMESAMA_LOG_FILE", "0")

warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient`",
    category=UserWarning,
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ORIGIN = "http://localhost:7843"
WRITE_HEADERS = {"origin": ORIGIN}

_SURVEILLES = ("data", "downloads", "scans")
_empreintes_avant: dict[str, dict[str, tuple[int, int]]] = {}


def _empreinte(racine: Path) -> dict[str, tuple[int, int]]:
    """Chemin -> (taille, mtime_ns). Pas de hash : deux parcours par run suffisent."""
    out: dict[str, tuple[int, int]] = {}
    if not racine.is_dir():
        return out
    for chemin in racine.rglob("*"):
        try:
            if not chemin.is_file():
                continue
            st = chemin.stat()
        except OSError:
            continue
        out[str(chemin.relative_to(racine))] = (st.st_size, st.st_mtime_ns)
    return out


def _ecarts(avant: dict, apres: dict) -> list[str]:
    lignes = []
    for cle in sorted(set(avant) | set(apres)):
        a, b = avant.get(cle), apres.get(cle)
        if a == b:
            continue
        if a is None:
            lignes.append(f"    + cree    {cle}  ({b[0]} o)")
        elif b is None:
            lignes.append(f"    - efface  {cle}  ({a[0]} o)")
        else:
            lignes.append(f"    ~ modifie {cle}  ({a[0]} -> {b[0]} o)")
    return lignes


def pytest_sessionstart(session):
    for nom in _SURVEILLES:
        _empreintes_avant[nom] = _empreinte(_RACINE_DEPOT / nom)


def _nettoyer_data_tests() -> None:
    """Le dossier de session est jetable : sans cela, chaque run en laisse un.

    Garde sur violation : s'il y a eu ecriture hors tmp_path, on preserve les
    donnees de la session pour pouvoir aller y regarder.
    """
    import shutil

    shutil.rmtree(_data_tests, ignore_errors=True)


def _violations() -> list[str]:
    fautes = []
    for nom in _SURVEILLES:
        ecarts = _ecarts(_empreintes_avant.get(nom, {}), _empreinte(_RACINE_DEPOT / nom))
        if ecarts:
            fautes.append(f"  {nom}/ :\n" + "\n".join(ecarts))
    return fautes


def pytest_sessionfinish(session, exitstatus):
    """Echoue le run si un test a touche aux donnees reelles.

    La detection double la prevention (ANIMESAMA_DATA_DIR) : celle-ci ne couvre
    que ce qui passe par DATA_DIR, et rien n'empeche un futur module d'ecrire
    ailleurs sous la racine du depot.
    """
    fautes = _violations()
    if not fautes:
        _nettoyer_data_tests()
        return
    # Le verdict d'abord : une console qui n'encode pas le rapport ne doit pas
    # transformer l'echec en succes.
    session.exitstatus = 1
    rapport = (
        "\n\n=================== ISOLATION VIOLEE ===================\n"
        "Des tests ont ecrit hors de leur tmp_path, dans les donnees reelles :\n"
        + "\n".join(fautes)
        + "\n-> le coupable doit passer par tmp_path, ou par ANIMESAMA_DATA_DIR"
        "\n   (pose pour toute la session en tete de tests/conftest.py).\n"
    )
    try:
        print(rapport)
    except Exception:
        sys.stderr.buffer.write(rapport.encode("ascii", "replace") + b"\n")

@pytest.fixture(scope="session")
def client():
    from web.api.app import create_app

    app = create_app()
    return TestClient(app, base_url="http://localhost")

@pytest.fixture
def logged_in(monkeypatch):
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_manager, "_logged_in", True)
    return auth_manager

@pytest.fixture(autouse=True)
def _reset_module_caches():
    import importlib
    _dirs_snapshot = None
    try:
        import engine.config.settings as _st
        _dirs_snapshot = (
            _st,
            _st.DOWNLOADS_DIR,
            _st.SCANS_DIR,
            _st._downloads_dir._default,
            _st._scans_dir._default,
        )
    except Exception:
        _dirs_snapshot = None
    yield
    if _dirs_snapshot is not None:
        try:
            _st, _dl, _sc, _dl_def, _sc_def = _dirs_snapshot
            _st.DOWNLOADS_DIR = _dl
            _st.SCANS_DIR = _sc
            _st._downloads_dir._default = _dl_def
            _st._scans_dir._default = _sc_def
        except Exception:
            pass
    for mod_name, fn_name in (
        ("engine.config.settings", "invalider_downloads_dir_cache"),
        ("engine.config.settings", "invalider_scans_dir_cache"),
        ("engine.library.scanner", "invalider_cache_dossiers"),
        ("engine.library.scanner", "invalider_cache_librairie"),
        ("engine.library.updates", "invalider_cache_updates"),
        ("engine.scraping.players", "clear_season_cache"),
    ):
        try:
            getattr(importlib.import_module(mod_name), fn_name)()
        except Exception:
            pass
    try:
        import engine.cache.cover_images as _ci
        with _ci._inflight_lock:
            _ci._inflight.clear()
    except Exception:
        pass
    try:
        import engine.cache.covers as _cov
        with _cov._covers_lock_thread:
            _cov._covers_cache.clear()
    except Exception:
        pass
    try:
        import engine.download._rate_limiter as _rl
        with _rl._domain_lock:
            _rl._recent_bans.clear()
            _rl._host_throttle.clear()
            _rl._domain_last_access.clear()
            _rl._domain_penalty_active.clear()
    except Exception:
        pass
    try:
        import engine.download.methods._proc_registry as _pr
        _pr.set_pause_state(False)
    except Exception:
        pass
