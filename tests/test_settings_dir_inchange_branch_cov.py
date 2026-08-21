import pytest

import engine.config.logging_setup  # noqa: F401

WRITE_HEADERS = {"origin": "http://localhost:7843"}

STOCKE = {
    "qualite": "auto",
    "thread_count": 16,
    "downloads_dir": "",
    "scans_dir": "E:\\scans",
    "notifications": True,
    "son_notif": True,
    "confirm_suppr": True,
    "skip_existants": True,
    "langue_defaut": "VOSTFR",
}


def _stocke() -> dict:
    return dict(STOCKE)


@pytest.fixture
def settings_io(monkeypatch):
    """Isole la route : load_settings rend STOCKE, save_settings capture, aucun disque touche."""
    import web.api.routes.settings as settings_mod

    capture = {}
    appels = []

    def _save(s):
        capture["s"] = dict(s)
        return True

    def _spy(chemin):
        appels.append(chemin)
        if chemin.startswith("E:"):
            return False, "boom-volume-disparu"
        return True, chemin

    monkeypatch.setattr(settings_mod, "load_settings", _stocke)
    monkeypatch.setattr(settings_mod, "save_settings", _save)
    monkeypatch.setattr(settings_mod, "_valider_dossier", _spy)
    capture["appels"] = appels
    return capture


def _corps_du_front(**override) -> dict:
    """Les 9 champs que web/static/js/app.js:73-83 reemet systematiquement, sans dirty-tracking."""
    corps = {
        "qualite": "auto",
        "thread_count": 16,
        "downloads_dir": "/nouveau/dossier",
        "scans_dir": "E:\\scans",
        "notifications": True,
        "son_notif": True,
        "confirm_suppr": True,
        "skip_existants": True,
        "langue_defaut": "VOSTFR",
    }
    corps.update(override)
    return corps


def test_champ_dossier_non_modifie_ne_bloque_pas_l_enregistrement(client, settings_io):
    """Un scans_dir reemis a l identique par le front ne doit ni etre revalide ni bloquer le POST."""
    r = client.post("/api/settings", headers=WRITE_HEADERS, json=_corps_du_front())
    assert r.status_code == 200
    corps = r.json()

    assert corps["ok"] is True, (
        f"enregistrement refuse par un champ non modifie : {corps.get('message')!r}"
    )
    assert "E:\\scans" not in settings_io["appels"], (
        f"scans_dir non modifie revalide (effet de bord mkdir) : {settings_io['appels']}"
    )
    assert settings_io["s"]["downloads_dir"] == "/nouveau/dossier"
    assert settings_io["s"]["scans_dir"] == "E:\\scans"


def test_downloads_dir_non_modifie_ne_bloque_pas_l_enregistrement(client, monkeypatch, settings_io):
    """Branche symetrique : un downloads_dir reemis a l identique ne doit pas non plus etre revalide."""
    import web.api.routes.settings as settings_mod

    stocke = _stocke()
    stocke["downloads_dir"] = "E:\\anime"
    stocke["scans_dir"] = ""
    monkeypatch.setattr(settings_mod, "load_settings", lambda: dict(stocke))

    r = client.post(
        "/api/settings",
        headers=WRITE_HEADERS,
        json=_corps_du_front(downloads_dir="E:\\anime", scans_dir="/nouveaux/scans"),
    )
    assert r.status_code == 200
    corps = r.json()

    assert corps["ok"] is True, (
        f"enregistrement refuse par un champ non modifie : {corps.get('message')!r}"
    )
    assert "E:\\anime" not in settings_io["appels"], (
        f"downloads_dir non modifie revalide (effet de bord mkdir) : {settings_io['appels']}"
    )
    assert settings_io["s"]["scans_dir"] == "/nouveaux/scans"
    assert settings_io["s"]["downloads_dir"] == "E:\\anime"


def test_champ_dossier_reellement_modifie_reste_refuse(client, settings_io):
    """Controle : le fail-fast legitime reste intact quand la valeur EST modifiee."""
    r = client.post(
        "/api/settings", headers=WRITE_HEADERS, json=_corps_du_front(scans_dir="E:\\autre")
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "boom-volume-disparu"}
    assert "E:\\autre" in settings_io["appels"]
    assert "s" not in settings_io
