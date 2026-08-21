"""Le trousseau Windows est commun à la machine : ses entrées étaient partagées
par les trois installations (sources, dossier de build, %LOCALAPPDATA%).

Se déconnecter dans l'une supprimait la clé Fernet des autres, dont les
cookies.enc devenaient indéchiffrables — et l'InvalidToken qui suivait n'était
traité nulle part. `email` et `password` souffraient du même défaut : ils sont
maintenant nommés par installation comme la clé, avec reprise de l'entrée
historique sans la détruire.
"""

import json
import logging
import sys
import types
from pathlib import Path

import pytest

from engine.auth import storage


class _PasswordDeleteError(Exception):
    pass


@pytest.fixture
def trousseau(monkeypatch):
    magasin: dict[str, str] = {}

    errors_mod = types.ModuleType("keyring.errors")
    errors_mod.PasswordDeleteError = _PasswordDeleteError

    def _set(app, user, value):
        magasin[user] = value

    def _delete(app, user):
        if user not in magasin:
            raise _PasswordDeleteError(user)
        del magasin[user]

    kr_mod = types.ModuleType("keyring")
    kr_mod.get_password = lambda app, user: magasin.get(user)
    kr_mod.set_password = _set
    kr_mod.delete_password = _delete
    kr_mod.errors = errors_mod

    monkeypatch.setitem(sys.modules, "keyring", kr_mod)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors_mod)
    return magasin


@pytest.fixture
def cookies_hors_projet(tmp_path, monkeypatch):
    cf = tmp_path / "cookies.enc"
    monkeypatch.setattr(storage, "_cookies_file", lambda: cf)
    return cf


def _nouvelle_cle() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


@pytest.mark.parametrize(
    "base", [storage.FERNET_KEY_LEGACY, storage.EMAIL_LEGACY, storage.PASSWORD_LEGACY]
)
def test_nom_propre_a_chaque_installation(base):
    a = storage._nom_par_installation(
        base, Path(r"C:\Users\x\AppData\Local\Programs\AnimeSama")
    )
    b = storage._nom_par_installation(base, Path(r"D:\projet"))
    assert a != b
    assert a.startswith(base + "_")
    assert a != base


@pytest.mark.parametrize(
    "base", [storage.FERNET_KEY_LEGACY, storage.EMAIL_LEGACY, storage.PASSWORD_LEGACY]
)
def test_nom_insensible_a_la_casse_du_chemin(base):
    assert storage._nom_par_installation(
        base, Path(r"C:\Programs\AnimeSama")
    ) == storage._nom_par_installation(base, Path(r"c:\programs\animesama"))


def test_les_trois_entrees_portent_la_meme_empreinte():
    """Une seule installation, une seule empreinte : sinon la reprise historique
    d'une entree ne dirait rien de l'etat des deux autres."""
    empreintes = {
        nom.rsplit("_", 1)[-1]
        for nom in (
            storage.FERNET_KEY_NAME,
            storage.EMAIL_KEY_NAME,
            storage.PASSWORD_KEY_NAME,
        )
    }
    assert len(empreintes) == 1


def test_identifiants_nus_repris_sans_etre_supprimes(trousseau):
    """Le meme patron que la cle Fernet : on adopte, on ne detruit pas — l'autre
    installation qui n'a pas encore migre s'en sert toujours."""
    trousseau[storage.EMAIL_LEGACY] = "flo@example.com"
    trousseau[storage.PASSWORD_LEGACY] = "s3cr3t"

    creds = storage.AuthStorage().load_credentials()

    assert creds == {"email": "flo@example.com", "password": "s3cr3t"}
    assert trousseau[storage.EMAIL_LEGACY] == "flo@example.com"
    assert trousseau[storage.PASSWORD_LEGACY] == "s3cr3t"
    assert trousseau[storage.EMAIL_KEY_NAME] == "flo@example.com"
    assert trousseau[storage.PASSWORD_KEY_NAME] == "s3cr3t"


def test_identifiants_ecrits_sous_le_nom_de_l_installation(trousseau):
    storage.AuthStorage().save_credentials("a@b.com", "pw")

    assert trousseau[storage.EMAIL_KEY_NAME] == "a@b.com"
    assert trousseau[storage.PASSWORD_KEY_NAME] == "pw"
    assert storage.EMAIL_LEGACY not in trousseau
    assert storage.PASSWORD_LEGACY not in trousseau


def test_deux_installations_ne_partagent_plus_leurs_identifiants(trousseau, monkeypatch):
    """Le symptome rapporte : « des fois on ne peut plus l'utiliser apres
    l'avoir utilise ». Se deconnecter ici ne doit plus vider le voisin."""
    voisin_email = storage._nom_par_installation(
        storage.EMAIL_LEGACY, Path(r"C:\Users\x\AppData\Local\Programs\AnimeSama")
    )
    voisin_pw = storage._nom_par_installation(
        storage.PASSWORD_LEGACY, Path(r"C:\Users\x\AppData\Local\Programs\AnimeSama")
    )
    assert voisin_email != storage.EMAIL_KEY_NAME

    trousseau[voisin_email] = "voisin@example.com"
    trousseau[voisin_pw] = "pw-voisin"
    storage.AuthStorage().save_credentials("moi@example.com", "pw-moi")

    monkeypatch.setattr(storage, "_cookies_file", lambda: Path("nexiste.pas"))
    storage.AuthStorage().clear_all()

    assert storage.EMAIL_KEY_NAME not in trousseau
    assert trousseau[voisin_email] == "voisin@example.com"
    assert trousseau[voisin_pw] == "pw-voisin"


def test_cle_legacy_reprise_sans_etre_supprimee(trousseau):
    from cryptography.fernet import Fernet

    legacy = _nouvelle_cle()
    trousseau[storage.FERNET_KEY_LEGACY] = legacy

    fernet = storage._get_fernet(allow_create=False)

    assert trousseau[storage.FERNET_KEY_LEGACY] == legacy
    assert trousseau[storage.FERNET_KEY_NAME] == legacy
    assert fernet.decrypt(Fernet(legacy.encode()).encrypt(b"ok")) == b"ok"


def test_nouvelle_installation_ecrit_sous_son_propre_nom(trousseau):
    storage._get_fernet(allow_create=True)
    assert storage.FERNET_KEY_NAME in trousseau
    assert storage.FERNET_KEY_LEGACY not in trousseau


def test_logout_ne_supprime_pas_les_entrees_nues(trousseau, cookies_hors_projet):
    """Les noms nus appartiennent aussi aux installations non migrees."""
    trousseau[storage.FERNET_KEY_LEGACY] = "cle-des-autres"
    trousseau[storage.EMAIL_LEGACY] = "vieux@example.com"
    trousseau[storage.PASSWORD_LEGACY] = "vieux-pw"
    trousseau[storage.FERNET_KEY_NAME] = "cle-locale"
    trousseau[storage.EMAIL_KEY_NAME] = "moi@example.com"
    trousseau[storage.PASSWORD_KEY_NAME] = "pw-moi"

    storage.AuthStorage().clear_all()

    assert trousseau[storage.FERNET_KEY_LEGACY] == "cle-des-autres"
    assert trousseau[storage.EMAIL_LEGACY] == "vieux@example.com"
    assert trousseau[storage.PASSWORD_LEGACY] == "vieux-pw"
    assert storage.FERNET_KEY_NAME not in trousseau
    assert storage.EMAIL_KEY_NAME not in trousseau
    assert storage.PASSWORD_KEY_NAME not in trousseau


def test_session_chiffree_avec_une_autre_cle_est_mise_a_l_ecart(
    trousseau, cookies_hors_projet, caplog
):
    from cryptography.fernet import Fernet

    autre = Fernet(Fernet.generate_key())
    charge = json.dumps({"cookies": [{"name": "a", "value": "b"}], "username": "flo"})
    cookies_hors_projet.write_text(autre.encrypt(charge.encode()).decode(), encoding="utf-8")
    trousseau[storage.FERNET_KEY_NAME] = _nouvelle_cle()

    with caplog.at_level(logging.WARNING, logger="engine.auth.storage"):
        assert storage.AuthStorage().load_session() is None

    ecarte = cookies_hors_projet.with_name(cookies_hors_projet.name + ".illisible")
    assert not cookies_hors_projet.exists()
    assert ecarte.exists()
    message = " ".join(r.getMessage() for r in caplog.records)
    assert "econnecte" in message
    assert "autre" in message.lower()


def test_deux_sessions_illisibles_ne_s_ecrasent_pas(trousseau, cookies_hors_projet):
    from cryptography.fernet import Fernet

    autre = Fernet(Fernet.generate_key())
    trousseau[storage.FERNET_KEY_NAME] = _nouvelle_cle()

    for _ in range(2):
        cookies_hors_projet.write_text(autre.encrypt(b"{}").decode(), encoding="utf-8")
        storage.AuthStorage().load_session()

    base = cookies_hors_projet.name
    assert cookies_hors_projet.with_name(base + ".illisible").exists()
    assert cookies_hors_projet.with_name(base + ".illisible-1").exists()


def test_cle_absente_ne_detruit_pas_la_session(trousseau, cookies_hors_projet, caplog):
    from cryptography.fernet import Fernet

    autre = Fernet(Fernet.generate_key())
    cookies_hors_projet.write_text(autre.encrypt(b"{}").decode(), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="engine.auth.storage"):
        assert storage.AuthStorage().load_session() is None

    # Le trousseau peut etre momentanement indisponible : on n'ecarte que ce
    # qu'on sait definitivement indechiffrable.
    assert cookies_hors_projet.exists()
    message = " ".join(r.getMessage() for r in caplog.records)
    assert "econnecte" in message


def test_session_valide_reste_lisible(trousseau, cookies_hors_projet):
    trousseau[storage.FERNET_KEY_NAME] = _nouvelle_cle()
    magasin = storage.AuthStorage()
    magasin.save_cookies([{"name": "remember_token", "value": "x"}], "flo")

    session = magasin.load_session()

    assert session is not None
    assert session["username"] == "flo"
    assert session["cookies"][0]["name"] == "remember_token"
