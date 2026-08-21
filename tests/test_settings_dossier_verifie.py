"""C13.a — dire où vont vraiment les fichiers, et ne pas fabriquer de dossier fantôme.

`_valider_dossier` cree le dossier absent au moment de la sauvegarde : une faute
de frappe fabriquait un dossier en silence. La sonde ci-dessous repond sans rien
creer, pour que l'interface puisse demander confirmation avant d'en arriver la.

`/api/health` n'exposait que la lettre de lecteur, jamais le chemin resolu — or
c'est le seul endroit qui sait ou les fichiers atterrissent reellement quand le
dossier configure est injoignable et que la resolution retombe sur le defaut.
"""

import asyncio

import engine.config.logging_setup  # noqa: F401
from web.api.routes.health import health
from web.api.routes.settings import verifier_dossier


def _sonde(chemin: str) -> dict:
    return asyncio.run(verifier_dossier(chemin=chemin))


def test_health_expose_le_chemin_reellement_utilise():
    disk = asyncio.run(health())["disk"]
    assert disk, "aucun disque rapporté"
    for label in ("downloads", "scans", "temp"):
        if label in disk:
            assert disk[label]["path"], f"{label} sans chemin résolu"


def test_sonde_signale_un_dossier_existant_et_inscriptible(tmp_path):
    d = _sonde(str(tmp_path))
    assert d["ok"] is True
    assert d["existe"] is True
    assert d["inscriptible"] is True
    assert d["chemin"] == str(tmp_path)


def test_sonde_ne_cree_jamais_le_dossier_absent(tmp_path):
    cible = tmp_path / "pas" / "encore" / "la"
    d = _sonde(str(cible))

    assert d["ok"] is True
    assert d["existe"] is False
    assert d["creable"] is True
    assert not cible.exists(), "la sonde a fabriqué le dossier"


def test_sonde_refuse_un_chemin_qui_est_un_fichier(tmp_path):
    fichier = tmp_path / "un.txt"
    fichier.write_text("x", encoding="utf-8")

    d = _sonde(str(fichier))
    assert d["ok"] is False
    assert d["existe"] is True
    assert "dossier" in d["message"].lower()


def test_chemin_vide_veut_dire_dossier_par_defaut():
    d = _sonde("")
    assert d["ok"] is True
    assert d["defaut"] is True


def test_sonde_signale_un_lecteur_introuvable():
    d = _sonde("Z:/inexistant/xyz")
    assert d["existe"] is False
    # Un lecteur absent n'est pas un dossier « a creer » : rien ne peut
    # l'accueillir, et l'enregistrement echouerait plus tard.
    assert d["creable"] is False
    assert d["ok"] is False


def test_sonde_ne_touche_pas_au_disque_pour_un_chemin_invalide():
    d = _sonde("\x00pas/un/chemin")
    assert d["ok"] is False
    assert d["existe"] is False
