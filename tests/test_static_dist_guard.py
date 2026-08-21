import logging

import engine.config.settings as settings_mod
import server


def _preparer_static(tmp_path, *, avec_dist: bool):
    static = tmp_path / "static"
    (static / "dist").mkdir(parents=True)
    (static / "index.html").write_text("<html></html>", encoding="utf-8")
    if avec_dist:
        (static / "dist" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return static


def test_dist_absent_logge_la_commande_de_build(tmp_path, monkeypatch, caplog):
    static = _preparer_static(tmp_path, avec_dist=False)
    monkeypatch.setattr(settings_mod, "STATIC_DIR", static)

    with caplog.at_level(logging.ERROR, logger="main"):
        ok = server._verifier_static_dir()

    assert ok is True
    messages = " ".join(r.message for r in caplog.records)
    assert "npm run build" in messages
    assert "npm install" in messages


def test_dist_present_ne_logge_rien(tmp_path, monkeypatch, caplog):
    static = _preparer_static(tmp_path, avec_dist=True)
    monkeypatch.setattr(settings_mod, "STATIC_DIR", static)

    with caplog.at_level(logging.DEBUG, logger="main"):
        ok = server._verifier_static_dir()

    assert ok is True
    assert caplog.records == []


def test_static_absent_reste_bloquant(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(settings_mod, "STATIC_DIR", tmp_path / "inexistant")

    with caplog.at_level(logging.ERROR, logger="main"):
        ok = server._verifier_static_dir()

    assert ok is False
