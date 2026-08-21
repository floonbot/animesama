from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAT = (ROOT / "packaging" / "build_exe.bat").read_text(encoding="utf-8", errors="replace")


def test_le_garde_fou_du_setup_perime_survit_a_no_installer():
    """« goto fin_installeur » sautait le renommage en .PERIME.exe : un installeur
    d'un build precedent restait a cote d'un dossier AnimeSama\\ tout neuf et
    reinstallait l'ancienne application sans rien dire."""
    saut = BAT.index("if defined ANIMESAMA_NO_INSTALLER")
    cible = BAT[saut:saut + 400]
    etiquette = [ligne for ligne in cible.splitlines() if ligne.strip().startswith("goto ")]

    assert etiquette, "le saut ANIMESAMA_NO_INSTALLER a disparu"
    destination = etiquette[0].strip().split()[1]
    garde = BAT.index("AnimeSama-Setup.PERIME.exe")

    assert BAT.index(f":{destination}") < garde, (
        f"le saut vers :{destination} contourne encore le garde-fou .PERIME"
    )


def test_le_dossier_non_supprime_arrete_le_build():
    """rmdir en echec (exe verrouille) laissait PyInstaller ecrire par-dessus :
    le paquet melangeait alors anciens et nouveaux fichiers."""
    i_rmdir = BAT.index("rmdir /s /q AnimeSama")
    i_pyinstaller = BAT.index("-m PyInstaller")
    entre_deux = BAT[i_rmdir:i_pyinstaller]

    assert "if exist AnimeSama (" in entre_deux
    assert "exit /b 1" in entre_deux


def test_le_port_encore_occupe_arrete_le_build():
    i_kill = BAT.index("taskkill /f /im AnimeSama.exe")
    i_pyinstaller = BAT.index("-m PyInstaller")
    entre_deux = BAT[i_kill:i_pyinstaller]

    assert entre_deux.count("netstat") >= 1
    assert "exit /b 1" in entre_deux


def test_le_tampon_de_build_est_ecrit_avant_pyinstaller():
    i_stamp = BAT.index("stamp_build.py")
    i_pyinstaller = BAT.index("-m PyInstaller")
    i_bundle = BAT.index("build.mjs")

    assert i_bundle < i_stamp < i_pyinstaller
    assert "exit /b 1" in BAT[i_stamp:i_pyinstaller], "un tampon manquant doit arreter le build"


def test_la_version_est_transmise_a_inno():
    assert "engine.version import APP_VERSION" in BAT
    assert "/DAppVersion=" in BAT


def test_la_comparaison_avec_l_installation_cloture_le_build():
    i_verif = BAT.index("verifier_installation.py")
    i_termine = BAT.index("TERMINE")

    assert i_verif < i_termine


def test_build_installer_transmet_aussi_la_version():
    autre = (ROOT / "packaging" / "build_installer.bat").read_text(
        encoding="utf-8", errors="replace"
    )

    assert "/DAppVersion=" in autre


def test_le_comparateur_lit_le_meme_tampon_que_l_application():
    from engine.version import TAMPON_NOM

    verif = (ROOT / "packaging" / "verifier_installation.py").read_text(encoding="utf-8")
    stamp = (ROOT / "packaging" / "stamp_build.py").read_text(encoding="utf-8")

    assert "TAMPON_NOM" in verif
    assert "TAMPON_NOM" in stamp
    assert TAMPON_NOM == "build-info.json"


def test_le_tampon_genere_est_ignore_par_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "web/static/build-info.json" in ignore
