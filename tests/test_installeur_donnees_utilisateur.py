"""L'installeur ne peut pas tourner sous pytest : ces tests verrouillent le script.

Le comportement a ete verifie a la main sur une installation de test (AppId dedie) :
reinstallation par-dessus des reglages complets -> les neuf cles survivent ;
desinstallation silencieuse -> data/ downloads/ scans/ conserves ; reponse « oui »
-> data/ seul supprime.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISS = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8", errors="replace")

_CLES_REGLAGES = (
    "qualite", "thread_count", "scans_dir", "notifications",
    "son_notif", "confirm_suppr", "skip_existants", "langue_defaut",
)


def test_les_reglages_existants_ne_sont_jamais_reecrits():
    """SaveStringToFile(..., False) sur un JSON ne portant que downloads_dir
    detruisait les huit autres reglages a chaque reinstallation."""
    corps = ISS[ISS.index("procedure CurStepChanged"):]
    garde = corps.index("if FileExists(Cible) then")
    ecriture = corps.index("SaveStringToFile")

    assert garde < ecriture, "l'ecriture doit etre gardee par l'existence du fichier"
    assert "exit;" in corps[garde:ecriture]


def test_la_page_du_dossier_est_sautee_en_mise_a_jour():
    assert "function ShouldSkipPage" in ISS
    assert "EstMiseAJour()" in ISS


def test_la_mise_a_jour_annonce_que_les_donnees_sont_conservees():
    assert "function UpdateReadyMemo" in ISS
    memo = ISS[ISS.index("function UpdateReadyMemo"):ISS.index("function JsonEscape")]
    assert "CONSERVEES" in memo


def test_la_desinstallation_demande_avant_de_supprimer_quoi_que_ce_soit():
    """La question unique Oui/Non est devenue trois cases independantes.

    Les trois suppressions n'ont ni la meme portee ni la meme gravite : des
    reglages se refont en une minute, le trousseau oblige a se reconnecter, des
    videos peuvent peser des centaines de gigaoctets. Le choix unique obligeait
    a tout garder ou tout perdre.
    """
    form = ISS[ISS.index("function DemanderOptions"):ISS.index("procedure EffacerDossier")]

    assert "CreateCustomForm" in form
    assert form.count("AjouterCase") >= 3, "trois choix independants attendus"
    assert "Result.Checked := False" in ISS, "tout doit etre decoche par defaut"
    assert "mrCancel" in form, "on doit pouvoir renoncer"


def test_rien_n_est_supprime_sans_case_cochee():
    """Chaque suppression est gardee par son propre drapeau, jamais par un autre."""
    bloc = ISS[ISS.index("procedure CurUninstallStepChanged"):]

    for drapeau in ("SupprData", "SupprTrousseau", "SupprMedias"):
        assert f"if {drapeau} then" in bloc, drapeau

    assert "if UninstallSilent" in bloc
    assert bloc.index("UninstallSilent") < bloc.index("DemanderOptions("), (
        "une desinstallation silencieuse ne doit rien supprimer : personne "
        "n'est la pour choisir"
    )


def test_la_suppression_des_videos_est_le_choix_le_plus_protege():
    """Le seul choix irreversible : decoche par defaut, confirme une seconde fois,
    et refuse par CheminEffacable si le chemin est une racine de disque."""
    bloc = ISS[ISS.index("function DemanderOptions"):]
    confirmation = bloc[bloc.index("if SupprMedias then"):][:700]

    assert "IRREVERSIBLE" in bloc
    assert "SuppressibleMsgBox" in confirmation
    assert "MB_DEFBUTTON2" in confirmation, "le defaut reste « non »"
    assert "IDNO" in confirmation, "sous /SUPPRESSMSGBOXES la reponse est « non »"
    assert "function CheminEffacable" in ISS


def test_un_msgbox_nu_bloquerait_une_desinstallation_silencieuse():
    """MsgBox de la section [Code] ignore /SUPPRESSMSGBOXES : la desinstallation
    restait bloquee pour toujours sur une boite que personne ne regarde."""
    bloc = ISS[ISS.index("[Code]"):]
    lignes = [
        ligne.strip() for ligne in bloc.splitlines()
        if "MsgBox(" in ligne and "SuppressibleMsgBox" not in ligne
    ]

    assert lignes == []


def test_installdelete_purge_les_vestiges_des_versions_precedentes():
    """Inno n'efface pas les fichiers absents du nouveau paquet : diag.html, le
    dossier js/ et un .pyd compile pour l'ancienne version de Python survivaient."""
    assert "[InstallDelete]" in ISS
    bloc = ISS[ISS.index("[InstallDelete]"):ISS.index("[Files]")]

    assert "{app}\\_internal" in bloc
    for garde in ("{app}\\data", "{app}\\downloads", "{app}\\scans"):
        assert garde not in bloc, f"{garde} ne doit jamais etre efface a l'installation"


def test_la_version_est_injectable_par_la_ligne_de_commande():
    assert "#ifndef AppVersion" in ISS


def test_l_appid_reste_fige_donc_la_reinstallation_conserve_les_donnees():
    assert "A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D" in ISS


def test_les_reglages_cites_dans_le_commentaire_existent_vraiment():
    from engine.config.user_settings import DEFAULT_SETTINGS

    for cle in _CLES_REGLAGES:
        assert cle in DEFAULT_SETTINGS
        assert cle in ISS, f"{cle} n'est plus cite dans l'avertissement de installer.iss"
