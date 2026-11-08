"""Notifications Windows natives (centre de notifications).

Mesure du 07/11/2026 : dans WebView2 sous pywebview, ``Notification.permission``
vaut « denied » et ``requestPermission()`` est refuse d'office. Les notifications
web « Anime termine » ne se sont donc jamais affichees dans l'application, et la
case « Notifications » des parametres ne commandait rien. Le serveur les emet
lui-meme : PowerShell 5.1 projette WinRT sans aucune dependance, et l'AUMID est
declare sous HKCU (methode documentee pour une application Win32 non empaquetee ;
l'installeur retire la cle a la desinstallation).
"""

import base64
import logging
import os
import subprocess
import sys
import threading
from xml.sax.saxutils import escape

log = logging.getLogger("engine.utils.notifications")

AUMID = "AnimeSama.Desktop"
_CLE_AUMID = rf"Software\Classes\AppUserModelId\{AUMID}"
_TIMEOUT_S = 20

_aumid_pret = False
_verrou = threading.Lock()


def _icone() -> str:
    from engine.config.settings import STATIC_DIR

    chemin = STATIC_DIR / "img" / "icone-notification.png"
    return str(chemin) if chemin.exists() else ""


def _declarer_aumid() -> bool:
    global _aumid_pret
    with _verrou:
        if _aumid_pret:
            return True
        try:
            import winreg

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _CLE_AUMID) as cle:
                winreg.SetValueEx(cle, "DisplayName", 0, winreg.REG_SZ, "AnimeSama")
                icone = _icone()
                if icone:
                    winreg.SetValueEx(cle, "IconUri", 0, winreg.REG_SZ, icone)
            _aumid_pret = True
        except OSError as e:
            log.debug(f"AUMID non déclaré : {e}")
        return _aumid_pret


def _xml_toast(titre: str, corps: str, silencieux: bool) -> str:
    audio = '<audio silent="true"/>' if silencieux else ""
    return (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{escape(titre[:120])}</text><text>{escape(corps[:300])}</text>"
        f"</binding></visual>{audio}</toast>"
    )


def _script(xml: str) -> str:
    xml_ps = xml.replace("'", "''")
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]\n"
        "[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]\n"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$x.LoadXml('{xml_ps}')\n"
        "$t = New-Object Windows.UI.Notifications.ToastNotification $x\n"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}').Show($t)\n"
    )


def _envoyer(titre: str, corps: str, silencieux: bool) -> None:
    from engine.download._engine_utils import NO_WINDOW_FLAGS

    encode = base64.b64encode(_script(_xml_toast(titre, corps, silencieux)).encode("utf-16-le")).decode()
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encode],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=_TIMEOUT_S,
            creationflags=NO_WINDOW_FLAGS,
        )
        if r.returncode != 0:
            log.info("notification Windows refusée : %s",
                     (r.stderr or b"").decode("utf-8", "replace").strip()[:300])
    except (OSError, subprocess.SubprocessError) as e:
        log.info(f"notification Windows impossible : {e}")


def _desactive() -> bool:
    # Chaque fin d'anime simulee par les tests ouvrirait sinon un vrai toast.
    return "pytest" in sys.modules


def coupees_par_windows() -> bool:
    """Windows les masque toutes (reglage global) ou masque celles de l'app.

    Mesure du 07/11/2026 chez l'utilisateur : ToastEnabled = 0 — le toast part
    sans erreur et n'apparait nulle part, d'ou l'avertissement dans les parametres.
    """
    if os.name != "nt":
        return False
    import winreg

    for chemin, valeur in (
        (r"Software\Microsoft\Windows\CurrentVersion\PushNotifications", "ToastEnabled"),
        (rf"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\{AUMID}", "Enabled"),
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chemin) as cle:
                if winreg.QueryValueEx(cle, valeur)[0] == 0:
                    return True
        except OSError:
            continue
    return False


def notifier(titre: str, corps: str = "") -> bool:
    """Affiche une notification si les reglages le permettent ; ne bloque jamais."""
    if os.name != "nt" or _desactive():
        return False
    from engine.config.user_settings import load_settings

    reglages = load_settings()
    if not reglages.get("notifications", True):
        return False
    if not _declarer_aumid():
        return False
    threading.Thread(
        target=_envoyer, args=(titre, corps, not reglages.get("son_notif", True)),
        daemon=True, name="notification",
    ).start()
    return True
