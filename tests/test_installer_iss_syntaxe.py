"""Regression : un commentaire Pascal ne doit pas contenir d'accolade.

En Inno Setup, `{ ... }` delimite un commentaire dans la section [Code]. Un
commentaire qui cite une constante Inno — « pas dans {app} », par exemple — est
donc referme par l'accolade de cette constante, et la fin de la phrase devient du
code. Vecu : `Error on line 211 ... Column 67: Identifier expected. Compile
aborted.` L'installeur n'etait plus genere, le build renommait le precedent en
AnimeSama-Setup.PERIME.exe, et rien d'autre ne le signalait — le .bat se contente
d'un « ECHEC ISCC » au milieu de sa sortie.

Ce controle est statique : il n'a besoin ni d'Inno Setup ni des 2 min 30 de
compilation, donc il tourne partout.
"""

from pathlib import Path

ISS = Path(__file__).resolve().parent.parent / "packaging" / "installer.iss"


def _section_code(texte: str) -> str:
    """Le [Code] seul : ailleurs, les accolades sont des constantes Inno."""
    bas = texte.lower()
    debut = bas.find("\n[code]")
    assert debut != -1, "section [Code] introuvable dans installer.iss"
    return texte[debut:]


def _commentaires_accolade(code: str) -> list[tuple[int, str]]:
    trouves: list[tuple[int, str]] = []
    i, ligne, dans_chaine = 0, 1, False
    while i < len(code):
        c = code[i]
        if c == "\n":
            ligne += 1
        elif c == "'":
            dans_chaine = not dans_chaine
        elif c == "{" and not dans_chaine:
            fin = code.find("}", i)
            if fin == -1:
                trouves.append((ligne, code[i + 1:]))
                break
            trouves.append((ligne, code[i + 1:fin]))
            ligne += code.count("\n", i, fin)
            i = fin
        i += 1
    return trouves


def test_aucun_commentaire_accolade_ne_contient_d_accolade():
    code = _section_code(ISS.read_text(encoding="utf-8", errors="replace"))
    fautifs = [(n, t) for n, t in _commentaires_accolade(code) if "{" in t]
    assert not fautifs, (
        "commentaire referme trop tot par une accolade — utilise // : "
        + "; ".join(f"ligne {n} : {t[:60]}" for n, t in fautifs)
    )


def test_aucun_deltree_ne_contourne_le_garde_fou():
    """Le seul appelant de DelTree doit etre EffacerDossier, qui verifie le chemin.

    Les chemins supprimes a la desinstallation viennent de user_settings.json,
    que l'utilisateur peut editer. Un downloads_dir valant « D:\\ » effacerait un
    disque entier. CheminEffacable refuse les racines ; encore faut-il qu'aucun
    DelTree ne passe a cote.
    """
    code = _section_code(ISS.read_text(encoding="utf-8", errors="replace"))
    appels = [
        n for n, ligne in enumerate(code.splitlines(), 1)
        if "DelTree(" in ligne and not ligne.strip().startswith(("//", "{"))
    ]
    assert len(appels) == 1, f"{len(appels)} appels a DelTree, lignes {appels}"

    corps = code[code.index("procedure EffacerDossier"):]
    corps = corps[:corps.index("\nprocedure ") + 1] if "\nprocedure " in corps else corps
    assert "CheminEffacable" in corps
    assert corps.index("CheminEffacable") < corps.index("DelTree(")


def test_la_desinstallation_silencieuse_ne_supprime_rien():
    """Personne n'est la pour choisir : le seul defaut sans mandat est « rien »."""
    code = _section_code(ISS.read_text(encoding="utf-8", errors="replace"))
    bloc = code[code.index("procedure CurUninstallStepChanged"):]
    assert "UninstallSilent" in bloc
    assert bloc.index("UninstallSilent") < bloc.index("DemanderOptions(")


def test_les_trois_suppressions_sont_independantes():
    """Un seul Oui/Non forcait a tout garder ou tout perdre."""
    code = _section_code(ISS.read_text(encoding="utf-8", errors="replace"))
    for drapeau in ("SupprData", "SupprTrousseau", "SupprMedias"):
        assert f"if {drapeau} then" in code, drapeau
    assert code.count("TNewCheckBox") >= 1


def test_la_suppression_des_medias_demande_une_seconde_confirmation():
    code = _section_code(ISS.read_text(encoding="utf-8", errors="replace"))
    bloc = code[code.index("if SupprMedias then"):]
    assert "SuppressibleMsgBox" in bloc[:600]
    assert "IDNO" in bloc[:600], "le defaut doit rester « non »"


def test_l_installation_ecrit_les_deux_dossiers():
    texte = ISS.read_text(encoding="utf-8", errors="replace")
    assert 'DownloadPage.Values[1]' in texte
    assert '"scans_dir"' in texte


def test_le_bundle_n_embarque_pas_les_donnees():
    """Lancer l'app depuis AnimeSama\\ y cree cookies.enc : ne pas le distribuer."""
    lignes = [
        l for l in ISS.read_text(encoding="utf-8", errors="replace").splitlines()
        if l.strip().startswith("Source:") and "BundleDir" in l
    ]
    assert lignes, "ligne [Files] du bundle introuvable"
    for l in lignes:
        assert "Excludes:" in l and "data" in l.split("Excludes:")[1], l
