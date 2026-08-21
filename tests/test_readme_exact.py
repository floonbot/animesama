"""Le README a deja menti une fois : ces tests confrontent ses affirmations au code.

Ils ne verifient pas la prose, seulement les faits verifiables mecaniquement — chemins
cites, valeurs numeriques, commandes, et absence de vestiges.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_aucune_trace_de_la_page_de_diagnostic_autonome():
    assert "diag.html" not in README
    assert "nouvel onglet" not in README
    assert "Diagnostic » intégrée" in README or "Diagnostic » dans l'app" in README


def test_les_chemins_cites_existent_tous():
    liens = re.findall(r"\]\((?!https?://|#)([^)]+)\)", README)
    manquants = [lien for lien in liens if not (ROOT / lien.split("#")[0]).exists()]

    assert manquants == []


def test_les_commandes_de_developpement_sont_celles_qui_passent():
    for commande in ("ruff check .", "mypy .", "pytest -q"):
        assert commande in README
    assert "pytest -q -p no:randomly" in README


def test_le_build_front_est_documente_avant_le_lancement():
    i_npm = README.index("npm run build")
    i_lancement = README.index("python desktop.py")

    assert i_npm < i_lancement
    assert "npm install" in README


def test_les_deux_scripts_de_build_sont_cites():
    assert "BUILD.bat" in README
    assert "packaging/build_exe.bat" in README


def test_le_port_annonce_est_celui_du_code():
    from engine.config.settings import HOST, PORT

    assert f"{HOST}:{PORT}" in README


def test_le_seuil_des_hotes_degrades_est_celui_du_code():
    from engine.observability.metrics import HOST_ALERT_MIN_ATTEMPTS, HOST_ALERT_SUCCESS_PCT

    assert f"**{HOST_ALERT_SUCCESS_PCT} %**" in README
    assert f"**{HOST_ALERT_MIN_ATTEMPTS}** tentatives" in README


def test_les_valeurs_par_defaut_annoncees_sont_celles_du_code():
    from engine.config.settings import DL_MAX_RETRIES, DL_RETRY_DELAY

    ligne = next(li for li in README.splitlines() if "DL_MAX_RETRIES" in li)

    assert f"(`{DL_MAX_RETRIES}`)" in ligne
    assert f"(`{DL_RETRY_DELAY}` s)" in ligne


def test_les_variables_d_environnement_citees_sont_lues_quelque_part():
    tableau = README[README.index("## ⚙️ Configuration"):README.index("### 🔐")]
    citees = set(re.findall(r"`([A-Z][A-Z0-9_]{3,})`", tableau))
    sources = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "engine").rglob("*.py")
    )

    inconnues = {v for v in citees if f'"{v}"' not in sources}
    assert inconnues == set()


def test_les_hotes_du_tableau_existent_dans_le_registre():
    tableau = README[README.index("| **sibnet**"):README.index("Un dix-septième module")]
    cites = set(re.findall(r"\|\s*\*\*([a-z0-9]+)\*\*", tableau))
    modules = {
        p.stem for p in (ROOT / "engine" / "download" / "extractor" / "hosts").glob("*.py")
        if p.stem != "__init__"
    }

    assert cites <= modules
    assert modules - cites == {"oneupload"}, "un hôte du registre n'est ni listé ni justifié"


def test_le_dossier_installe_annonce_est_celui_de_l_installeur():
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8", errors="replace")

    assert "{localappdata}\\Programs\\AnimeSama" in iss
    assert "%LOCALAPPDATA%\\Programs\\AnimeSama" in README


def test_le_comportement_des_donnees_est_documente():
    section = README[README.index("### Ce que devient ta configuration"):]
    section = section[:section.index("## 🚀")]

    assert "conservées" in section
    assert "demande" in section
    assert "Jamais touchés" in section


def test_le_depannage_couvre_le_blackhole_dns():
    depannage = README[README.index("## 🩺 Dépannage"):]

    assert "DNS" in depannage
    assert "1.1.1.1" in depannage
    assert "8.8.8.8" in depannage


def test_le_message_de_blackhole_cite_est_bien_celui_du_code():
    source = (ROOT / "engine" / "utils" / "security.py").read_text(encoding="utf-8")
    extrait = "Hôte redirigé vers une adresse locale par ton DNS"

    assert extrait in source
    assert extrait in README


@pytest.mark.parametrize("commande", [
    "python -c \"import server; server.start_server()\"",
])
def test_le_lancement_sans_fenetre_documente_est_valide(commande):
    import server

    assert commande in README
    assert hasattr(server, "start_server")
    assert not (ROOT / "server.py").read_text(encoding="utf-8").count('__name__ == "__main__"')
