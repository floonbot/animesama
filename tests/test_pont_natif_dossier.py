"""C13.a — le sélecteur de dossier natif de la fenêtre de bureau.

Taper « D:\\MesAnimes » a la main est une source d'erreurs, mais l'interface est
aussi joignable depuis un navigateur : le pont doit exister sans jamais etre
obligatoire. Ces tests verrouillent le contrat cote Python ; la degradation
cote front est verifiee en e2e (aucun `window.pywebview` dans un navigateur).
"""

import sys
import types

import pytest

import desktop


class _FausseFenetre:
    def __init__(self, retour=None, exc=None):
        self.retour = retour
        self.exc = exc
        self.appels = []

    def create_file_dialog(self, dialog_type, directory=""):
        self.appels.append((dialog_type, directory))
        if self.exc is not None:
            raise self.exc
        return self.retour


@pytest.fixture
def faux_webview(monkeypatch):
    mod = types.ModuleType("webview")
    mod.FOLDER_DIALOG = 20
    mod.windows = []
    monkeypatch.setitem(sys.modules, "webview", mod)
    return mod


def test_le_pont_rend_le_dossier_choisi(faux_webview):
    pont = desktop.PontNatif()
    pont._fenetre = _FausseFenetre(retour=("D:\\MesAnimes",))

    assert pont.choisir_dossier() == "D:\\MesAnimes"
    assert pont._fenetre.appels == [(faux_webview.FOLDER_DIALOG, "")]


def test_le_dossier_de_depart_est_transmis(faux_webview):
    pont = desktop.PontNatif()
    pont._fenetre = _FausseFenetre(retour=["E:\\anime"])

    assert pont.choisir_dossier("E:\\") == "E:\\anime"
    assert pont._fenetre.appels[0][1] == "E:\\"


def test_annuler_le_selecteur_rend_une_chaine_vide(faux_webview):
    pont = desktop.PontNatif()
    pont._fenetre = _FausseFenetre(retour=None)
    assert pont.choisir_dossier() == ""

    pont._fenetre = _FausseFenetre(retour=())
    assert pont.choisir_dossier() == ""


def test_sans_fenetre_le_pont_ne_leve_pas(faux_webview):
    assert desktop.PontNatif().choisir_dossier() == ""


def test_le_pont_retombe_sur_la_fenetre_courante(faux_webview):
    fen = _FausseFenetre(retour=["C:\\x"])
    faux_webview.windows = [fen]
    assert desktop.PontNatif().choisir_dossier() == "C:\\x"


def test_un_selecteur_en_echec_ne_casse_pas_l_interface(faux_webview):
    pont = desktop.PontNatif()
    pont._fenetre = _FausseFenetre(exc=RuntimeError("pas de GUI"))
    assert pont.choisir_dossier() == ""


def test_seule_la_methode_voulue_est_exposee():
    # pywebview publie tout attribut public de l'objet js_api et *descend* dans
    # ceux qui ne sont pas appelables : une fenetre publique exposerait toutes
    # les methodes de Window a la page.
    exposes = [n for n in dir(desktop.PontNatif()) if not n.startswith("_")]
    assert exposes == ["choisir_dossier"]
