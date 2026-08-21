import json
import re
import sys
from pathlib import Path

import pytest

import engine.version as version_mod

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tampon(tmp_path, monkeypatch):
    """Redirige build-info.json vers tmp et fait croire au mode frozen."""
    cible = tmp_path / version_mod.TAMPON_NOM
    monkeypatch.setattr(version_mod, "chemin_tampon", lambda: cible)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    return cible


def test_version_unique_entre_pyproject_et_le_code():
    """Trois copies du numero de version avaient deja diverge : pyproject reste la
    declaration du paquet, engine.version celle du code, un test les tient ensemble."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)

    assert m, "pyproject.toml ne declare plus de version"
    assert m.group(1) == version_mod.APP_VERSION


def test_installer_iss_a_le_meme_repli_de_version():
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'#define\s+AppVersion\s+"([^"]+)"', iss)

    assert m, "installer.iss ne declare plus de repli AppVersion"
    assert m.group(1) == version_mod.APP_VERSION


def test_app_et_health_ne_recodent_plus_la_version_en_dur():
    for rel in ("web/api/app.py", "web/api/routes/health.py"):
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "APP_VERSION" in source, rel
        assert '"2.0.0"' not in source, f"{rel} recode la version en dur"


def test_sans_tampon_le_paquet_se_declare_sans_horodatage(tampon):
    ident = version_mod.identite_build()

    assert ident["source"] == "paquet_sans_tampon"
    assert ident["built_at"] is None
    assert "sans horodatage" in version_mod.description_build()


def test_le_tampon_donne_la_date_et_l_empreinte_du_paquet(tampon):
    tampon.write_text(json.dumps({
        "version": "2.0.0",
        "built_at": 1786000000.0,
        "built_at_iso": "2026-08-06T09:06:40",
        "front": "abc123def456",
        "git": "deadbee",
    }), encoding="utf-8")

    ident = version_mod.identite_build()

    assert ident["source"] == "paquet"
    assert ident["built_at"] == 1786000000.0
    assert ident["front"] == "abc123def456"
    assert "deadbee" in version_mod.description_build()


def test_un_tampon_illisible_ne_fait_pas_planter_le_demarrage(tampon):
    tampon.write_text("{ ceci n'est pas du JSON", encoding="utf-8")

    ident = version_mod.identite_build()

    assert ident["source"] == "paquet_sans_tampon"


def test_hors_frozen_un_tampon_residuel_ne_ment_pas(tmp_path, monkeypatch):
    """BUILD.bat laisse build-info.json dans l'arbre de travail : lancer les sources
    juste apres ne doit pas faire croire qu'on execute le paquet."""
    cible = tmp_path / version_mod.TAMPON_NOM
    cible.write_text(json.dumps({"built_at": 1786000000.0, "front": "x"}), encoding="utf-8")
    monkeypatch.setattr(version_mod, "chemin_tampon", lambda: cible)
    monkeypatch.delattr(sys, "frozen", raising=False)

    ident = version_mod.identite_build()

    assert ident["source"] == "sources"
    assert ident["built_at"] is None
    assert "sources de developpement" in version_mod.description_build()


def test_health_expose_l_identite_du_build(client):
    body = client.get("/api/health").json()

    assert body["version"] == version_mod.APP_VERSION
    assert body["build"]["version"] == version_mod.APP_VERSION
    assert body["build"]["source"] in ("sources", "paquet", "paquet_sans_tampon", "inconnu")


def test_le_diagnostic_affiche_la_date_du_paquet(client):
    src = client.get("/js/pages/diag.js").text

    assert "health.build" in src
    assert "sources de développement" in src
