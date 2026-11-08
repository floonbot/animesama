"""Namespacer la clé Fernet par installation crée une entrée de trousseau par
installation : la désinstallation doit la reprendre, sinon elle s'accumule dans
le gestionnaire d'identifiants Windows. Elle ne doit jamais toucher l'entrée
historique, que d'autres installations utilisent encore.
"""

import sys
from pathlib import Path

import pytest

import desktop
from engine.auth import storage

ROOT = Path(__file__).resolve().parent.parent
ISS = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def trousseau(monkeypatch):
    magasin: dict[str, str] = {}
    monkeypatch.setattr(storage, "_kr_get", lambda u: magasin.get(u))
    monkeypatch.setattr(storage, "_kr_set", lambda u, v: magasin.__setitem__(u, v))
    monkeypatch.setattr(storage, "_kr_delete", lambda u: magasin.pop(u, None))
    return magasin


def test_purge_supprime_la_cle_de_cette_installation(trousseau):
    trousseau[storage.FERNET_KEY_NAME] = "locale"

    storage.purger_cle_installation()

    assert storage.FERNET_KEY_NAME not in trousseau


def test_purge_epargne_la_cle_des_autres_installations(trousseau):
    trousseau[storage.FERNET_KEY_LEGACY] = "partagee"
    trousseau[storage.FERNET_KEY_NAME] = "locale"

    storage.purger_cle_installation()

    assert trousseau[storage.FERNET_KEY_LEGACY] == "partagee"


def test_purge_sans_cle_ne_leve_pas(trousseau):
    storage.purger_cle_installation()


def test_option_ligne_de_commande_purge_sans_ouvrir_de_fenetre(monkeypatch):
    appels: list = []
    monkeypatch.setattr(storage, "purger_cle_installation", lambda: appels.append(True))
    monkeypatch.setattr(sys, "argv", ["AnimeSama.exe", desktop.OPTION_PURGE_TROUSSEAU])

    class _InterditWebview:
        @staticmethod
        def create_window(*a, **k):
            pytest.fail("une fenêtre a été créée pendant la purge")

        @staticmethod
        def start(*a, **k):
            pytest.fail("webview.start appelé pendant la purge")

    monkeypatch.setitem(sys.modules, "webview", _InterditWebview)
    monkeypatch.setattr(desktop.server, "start_server", lambda *a, **k: pytest.fail("serveur démarré"))

    desktop.main()

    assert appels == [True]


def test_lancement_normal_ne_purge_rien(monkeypatch):
    appels: list = []
    monkeypatch.setattr(storage, "purger_cle_installation", lambda: appels.append(True))
    monkeypatch.setattr(sys, "argv", ["AnimeSama.exe"])
    monkeypatch.setattr(desktop.server, "wait_for_server", lambda *a, **k: True)
    monkeypatch.setattr(desktop.server, "installation_en_ecoute", lambda *a, **k: "")

    class _FakeWebview:
        @staticmethod
        def create_window(*a, **k):
            return object()

        @staticmethod
        def start(*a, **k):
            return None

    monkeypatch.setitem(sys.modules, "webview", _FakeWebview)

    desktop.main()

    assert appels == []


def test_la_purge_du_trousseau_est_un_choix_a_part_entiere():
    """Elle etait couplee a la suppression des donnees ; elle ne l'est plus.

    Garder ses reglages tout en retirant ses identifiants du trousseau est un cas
    reel — on desinstalle d'une machine partagee sans vouloir tout reconfigurer
    ailleurs. L'inverse aussi : repartir de zero cote reglages en gardant sa
    session. Les deux sont desormais des cases distinctes.
    """
    bloc = ISS[ISS.index("procedure CurUninstallStepChanged"):]

    assert desktop.OPTION_PURGE_TROUSSEAU in bloc
    purge = bloc.index(desktop.OPTION_PURGE_TROUSSEAU)

    garde = bloc.index("if SupprTrousseau then")
    assert garde < purge, "la purge doit etre gardee par sa propre case"

    donnees = bloc.index("EffacerDossier(DataDir")
    assert purge < donnees, "l'exe doit tourner avant que ses fichiers ne disparaissent"
