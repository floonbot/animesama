import logging

import pytest

from engine.config import logging_setup as ls
from engine.observability.context import task_context


@pytest.fixture
def _clean_root():
    """Racine sans handler de fichier, quel que soit ce qui a tourne avant.

    server.py appelle maybe_install_file_logging() a l'import, et le journal
    disque est actif par defaut : tout test important server laisse donc un
    _AppFileHandler attache. install_file_logging est idempotent — il aurait
    rendu CE handler-la au lieu d'en creer un, et ces tests echouaient en ordre
    aleatoire seulement.
    """
    from engine.observability.log_ring import log_ring

    root = logging.getLogger()
    fichiers = [h for h in root.handlers if _is_app_file_handler(h)]
    for h in fichiers:
        root.removeHandler(h)
    before = list(root.handlers)
    ring_attached = log_ring in root.handlers
    yield
    for h in list(root.handlers):
        if h not in before:
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
    log_ring.clear()
    if ring_attached and log_ring not in root.handlers:
        root.addHandler(log_ring)
    for h in fichiers:
        root.addHandler(h)


def _is_app_file_handler(h):
    return isinstance(h, ls._AppFileHandler)


def test_install_file_logging_writes_with_tid(tmp_path, _clean_root):
    p = tmp_path / "logs" / "app.log"
    h = ls.install_file_logging(str(p))
    assert _is_app_file_handler(h)
    log = logging.getLogger("test.file")
    log.setLevel(logging.INFO)
    with task_context("fid123"):
        log.warning("hello file")
    h.flush()
    content = p.read_text(encoding="utf-8")
    assert "hello file" in content
    assert "[fid123]" in content
    assert "WARNING" in content


def test_file_log_scrubs_url_in_traceback(tmp_path, _clean_root):
    p = tmp_path / "app.log"
    ls.install_file_logging(str(p))
    log = logging.getLogger("test.file.trace")
    log.setLevel(logging.INFO)
    try:
        raise RuntimeError("boom https://cdn.example.com/v.m3u8?token=SECRETXYZ&sig=zzz")
    except RuntimeError:
        log.exception("download failed")
    for h in logging.getLogger().handlers:
        if _is_app_file_handler(h):
            h.flush()
    content = p.read_text(encoding="utf-8")
    assert "download failed" in content
    assert "RuntimeError" in content
    assert "SECRETXYZ" not in content
    assert "sig=zzz" not in content


def test_file_log_scrubs_url_in_message(tmp_path, _clean_root):
    p = tmp_path / "app.log"
    ls.install_file_logging(str(p))
    log = logging.getLogger("test.file.msg")
    log.setLevel(logging.INFO)
    log.warning("got https://h/v.m3u8?token=SECRETMSG&e=1")
    for h in logging.getLogger().handlers:
        if _is_app_file_handler(h):
            h.flush()
    content = p.read_text(encoding="utf-8")
    assert "SECRETMSG" not in content
    assert "got https://h/v.m3u8" in content


def test_install_file_logging_idempotent(tmp_path, _clean_root):
    p = tmp_path / "app.log"
    ls.install_file_logging(str(p))
    ls.install_file_logging(str(p))
    root = logging.getLogger()
    assert sum(1 for h in root.handlers if _is_app_file_handler(h)) == 1


# Le journal sur disque est actif par defaut depuis C9 : l'anneau memoire ne
# garde que 400 lignes et meurt avec le processus, donc « ce qui s'est passe
# hier » n'existait nulle part.
def test_le_journal_sur_disque_est_actif_par_defaut(tmp_path, monkeypatch, _clean_root):
    monkeypatch.delenv("ANIMESAMA_LOG_FILE", raising=False)
    monkeypatch.setattr(ls, "_default_log_path", lambda: str(tmp_path / "app.log"))

    h = ls.maybe_install_file_logging()

    assert _is_app_file_handler(h)
    assert (tmp_path / "app.log").exists()


def test_la_variable_peut_couper_le_journal(tmp_path, monkeypatch, _clean_root):
    monkeypatch.setattr(ls, "_default_log_path", lambda: str(tmp_path / "app.log"))
    for valeur in ("0", "false", "off", "NO"):
        monkeypatch.setenv("ANIMESAMA_LOG_FILE", valeur)
        assert ls.maybe_install_file_logging() is None, valeur
    assert not (tmp_path / "app.log").exists()


def test_la_variable_peut_choisir_le_chemin(tmp_path, monkeypatch, _clean_root):
    voulu = tmp_path / "ailleurs" / "trace.log"
    monkeypatch.setenv("ANIMESAMA_LOG_FILE", str(voulu))

    h = ls.maybe_install_file_logging()

    assert _is_app_file_handler(h)
    assert voulu.exists()


def test_un_dossier_non_inscriptible_le_dit_au_lieu_de_se_taire(
    tmp_path, monkeypatch, _clean_root, caplog
):
    monkeypatch.delenv("ANIMESAMA_LOG_FILE", raising=False)
    monkeypatch.setattr(ls, "install_file_logging", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING):
        assert ls.maybe_install_file_logging() is None

    assert any("Journal sur disque indisponible" in r.message for r in caplog.records)
