import json
import logging
import os
import threading
from pathlib import Path

from engine.config.settings import DATA_DIR
from engine.version import empreinte_installation

log = logging.getLogger("engine.auth.storage")

COOKIES_FILE = DATA_DIR / "cookies.enc"
KEYRING_APP  = "AnimeDownloader"

COOKIES_FILE_MAX_SIZE = 1 * 1024 * 1024

FERNET_KEY_LEGACY = "fernet_key"
EMAIL_LEGACY      = "email"
PASSWORD_LEGACY   = "password"

_fernet_init_lock = threading.Lock()


def _empreinte_installation(racine: Path | None = None) -> str:
    # Une seule source : /api/health publie la meme, desktop.py la compare.
    return empreinte_installation(racine)


def _nom_par_installation(base: str, racine: Path | None = None) -> str:
    """Une entree de trousseau par installation, derivee du dossier d'installation.

    Le trousseau Windows est commun a la machine : les entrees nues `fernet_key`,
    `email` et `password` etaient donc partagees par les sources, le dossier de
    build et l'installation de %LOCALAPPDATA%. Se deconnecter dans l'une les
    supprimait pour les autres — d'ou le « des fois on ne peut plus l'utiliser
    apres l'avoir utilise » rapporte par l'utilisateur.
    """
    return f"{base}_{_empreinte_installation(racine)}"


# Meme chaine qu'avant pour la cle Fernet : la changer rendrait illisible le
# cookies.enc deja sur disque.
FERNET_KEY_NAME = _nom_par_installation(FERNET_KEY_LEGACY)
EMAIL_KEY_NAME    = _nom_par_installation(EMAIL_LEGACY)
PASSWORD_KEY_NAME = _nom_par_installation(PASSWORD_LEGACY)


def _cookies_file():
    return COOKIES_FILE

def _kr_get(username: str) -> str | None:
    try:
        import keyring
        return keyring.get_password(KEYRING_APP, username)
    except Exception as e:
        log.warning(f"keyring.get_password({username}) : {e}")
        return None

def _kr_set(username: str, value: str) -> None:
    try:
        import keyring
        keyring.set_password(KEYRING_APP, username, value)
    except Exception as e:
        log.warning(f"keyring.set_password({username}) : {e}")

def _kr_delete(username: str) -> None:
    try:
        import keyring
        from keyring.errors import PasswordDeleteError
        try:
            keyring.delete_password(KEYRING_APP, username)
        except PasswordDeleteError:
            pass
    except Exception as e:
        log.warning(f"keyring.delete_password({username}) : {e}")

def purger_cle_installation() -> None:
    """Retire la cle Fernet de cette installation, a la desinstallation.

    Jamais FERNET_KEY_LEGACY : les installations qui n'ont pas encore migre s'en
    servent toujours, et la supprimer rendrait leurs cookies.enc illisibles —
    exactement le defaut que le nommage par installation corrige.
    """
    _kr_delete(FERNET_KEY_NAME)
    log.info("Clé Fernet de cette installation retirée du trousseau")

def _reprendre_legacy(nom_propre: str, nom_legacy: str, quoi: str) -> str | None:
    """Adopte l'entree historique sous le nom de cette installation, sans la detruire.

    L'entree nue n'est jamais supprimee : les autres installations peuvent encore
    s'en servir tant qu'elles n'ont pas migre.
    """
    legacy = _kr_get(nom_legacy)
    if not legacy:
        return None
    _kr_set(nom_propre, legacy)
    log.info("%s repris sous un nom propre à cette installation", quoi)
    return legacy

def _reprendre_cle_legacy() -> str | None:
    return _reprendre_legacy(FERNET_KEY_NAME, FERNET_KEY_LEGACY, "Clé Fernet historique")

def _get_fernet(*, allow_create: bool = True):
    from cryptography.fernet import Fernet
    key = _kr_get(FERNET_KEY_NAME) or _reprendre_cle_legacy()
    if not key:
        if not allow_create:
            raise RuntimeError("Clé Fernet absente du trousseau")
        with _fernet_init_lock:
            key = _kr_get(FERNET_KEY_NAME) or _reprendre_cle_legacy()
            if not key:
                key = Fernet.generate_key().decode()
                _kr_set(FERNET_KEY_NAME, key)
                log.debug("Nouvelle clé Fernet générée dans le trousseau")
    return Fernet(key.encode())

def _cle_incompatible(exc: BaseException) -> bool:
    try:
        from cryptography.fernet import InvalidToken
    except ImportError:
        return False
    return isinstance(exc, InvalidToken)

def _encrypt(text: str) -> str:
    try:
        return _get_fernet(allow_create=True).encrypt(text.encode()).decode()
    except Exception as e:
        log.error(f"Erreur chiffrement : {e}")
        raise

def _decrypt(text: str) -> str:
    return _get_fernet(allow_create=False).decrypt(text.encode()).decode()

class AuthStorage:

    def save_credentials(self, email: str, password: str) -> None:
        _kr_set(EMAIL_KEY_NAME,    email)
        _kr_set(PASSWORD_KEY_NAME, password)
        log.debug("Credentials sauvegardés dans le trousseau")

    def load_credentials(self) -> dict | None:
        email = _kr_get(EMAIL_KEY_NAME) or _reprendre_legacy(
            EMAIL_KEY_NAME, EMAIL_LEGACY, "Identifiant historique"
        )
        password = _kr_get(PASSWORD_KEY_NAME) or _reprendre_legacy(
            PASSWORD_KEY_NAME, PASSWORD_LEGACY, "Mot de passe historique"
        )
        if not email or not password:
            return None
        return {"email": email, "password": password}

    def save_cookies(self, cookies: list, username: str = "") -> None:
        cf = _cookies_file()
        try:
            raw = json.dumps({"cookies": cookies, "username": username or ""})
            cf.parent.mkdir(parents=True, exist_ok=True)
            tmp = cf.with_suffix(".enc.tmp")
            tmp.write_text(_encrypt(raw), encoding="utf-8")
            try:
                # Quasi no-op sous Windows (ne bascule que le flag lecture seule) :
                # la confidentialite repose sur le chiffrement Fernet et les ACL du profil.
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, cf)
            log.debug(f"{len(cookies)} cookies sauvegardés")
        except Exception as e:
            log.error(f"Sauvegarde cookies impossible : {e}")
            try:
                tmp = cf.with_suffix(".enc.tmp")
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    def load_session(self) -> dict | None:
        cf = _cookies_file()
        if not cf.exists():
            return None
        try:
            try:
                size = cf.stat().st_size
                if size > COOKIES_FILE_MAX_SIZE:
                    log.warning(
                        f"cookies.enc trop gros ({size} octets), ignoré"
                    )
                    return None
            except OSError:
                pass

            raw = cf.read_text(encoding="utf-8").strip()
            if not raw:
                return None
            try:
                clair = _decrypt(raw)
            except Exception as e:
                self._session_indechiffrable(cf, e)
                return None
            data = json.loads(clair)
            if isinstance(data, list):
                return {"cookies": data, "username": ""}
            if not isinstance(data, dict):
                log.warning("Format de session inattendu")
                return None
            cookies = data.get("cookies")
            if isinstance(cookies, list) and len(cookies) > 1000:
                log.warning(f"{len(cookies)} cookies — suspect, ignoré")
                return None
            return data
        except Exception as e:
            log.warning(f"Session illisible : {e}")
            return None

    @staticmethod
    def _session_indechiffrable(cf, cause: BaseException) -> None:
        """Une session illisible est un cul-de-sac : la signaler et la degager.

        Sans mise a l'ecart, chaque demarrage rejouait le meme echec en silence
        et l'utilisateur restait deconnecte sans savoir pourquoi. On n'ecarte
        que l'InvalidToken — un trousseau momentanement indisponible redeviendra
        lisible, alors qu'une cle differente ne le redeviendra jamais.
        """
        if not _cle_incompatible(cause):
            log.warning(
                "Session chiffrée illisible (%s) — reconnecte-toi pour en créer une nouvelle.",
                cause,
            )
            return
        cible = cf.with_name(cf.name + ".illisible")
        n = 1
        while cible.exists():
            cible = cf.with_name(f"{cf.name}.illisible-{n}")
            n += 1
        try:
            os.replace(str(cf), str(cible))
        except OSError:
            log.warning("Session illisible : mise à l'écart de %s impossible", cf, exc_info=True)
            return
        log.warning(
            "Session chiffrée avec une autre clé — une autre installation d'Anime-Sama "
            "a régénéré la clé du trousseau. Fichier mis à l'écart sous « %s ».\n"
            "→ Reconnecte-toi : une nouvelle session sera créée.",
            cible,
        )

    def load_cookies(self) -> list:
        s = self.load_session()
        cookies = s.get("cookies") if isinstance(s, dict) else None
        return cookies if isinstance(cookies, list) else []

    def clear(self) -> None:
        cf = _cookies_file()
        if cf.exists():
            try:
                cf.unlink()
            except Exception as e:
                log.warning(f"Suppression cookies.enc : {e}")
        log.debug("Cookies effacés")

    def clear_all(self) -> None:
        self.clear()
        # Jamais les noms nus : ils appartiennent aussi aux autres installations,
        # qui n'ont peut-etre pas encore migre.
        _kr_delete(EMAIL_KEY_NAME)
        _kr_delete(PASSWORD_KEY_NAME)
        _kr_delete(FERNET_KEY_NAME)
        log.debug("Credentials effacés du trousseau")
