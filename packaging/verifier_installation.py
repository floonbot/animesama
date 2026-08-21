"""Compare le paquet qui vient d'etre construit a celui qui est installe.

Le raccourci du Bureau lance %LOCALAPPDATA%\\Programs\\AnimeSama, jamais le
dossier AnimeSama\\ du depot. Un rebuild qui n'est pas suivi de l'installeur
laisse donc l'utilisateur devant l'ancienne application, sans qu'aucun signal ne
le dise. Ce script est ce signal : appele en fin de build_exe.bat, il compare les
deux tampons de build et parle fort quand ils divergent.
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.version import TAMPON_NOM  # noqa: E402

APP_ID = "{A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D}_is1"
_SOUS_CLE = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
_RELATIF_TAMPON = Path("_internal") / "web" / "static" / TAMPON_NOM
_RELATIF_EXE = Path("AnimeSama.exe")


def _chemin_registre() -> Path | None:
    try:
        import winreg
    except ImportError:
        return None
    for ruche in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(ruche, _SOUS_CLE) as cle:
                valeur, _ = winreg.QueryValueEx(cle, "InstallLocation")
        except OSError:
            continue
        if isinstance(valeur, str) and valeur.strip():
            return Path(valeur.strip())
    return None


def chemin_installe() -> Path | None:
    depuis_registre = _chemin_registre()
    if depuis_registre is not None and (depuis_registre / _RELATIF_EXE).is_file():
        return depuis_registre
    local = os.environ.get("LOCALAPPDATA")
    if local:
        defaut = Path(local) / "Programs" / "AnimeSama"
        if (defaut / _RELATIF_EXE).is_file():
            return defaut
    return None


def _tampon(racine: Path) -> dict:
    try:
        data = json.loads((racine / _RELATIF_TAMPON).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _horodatage(racine: Path) -> float:
    tampon = _tampon(racine)
    brut = tampon.get("built_at")
    if isinstance(brut, int | float):
        return float(brut)
    try:
        return (racine / _RELATIF_EXE).stat().st_mtime
    except OSError:
        return 0.0


def _date(ts: float) -> str:
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts)) if ts else "date inconnue"


def comparer(construit: Path, installe: Path) -> tuple[bool, str]:
    """(identiques, message). Compare l'empreinte front, l'horodatage a defaut."""
    front_construit = _tampon(construit).get("front")
    front_installe = _tampon(installe).get("front")
    ts_construit, ts_installe = _horodatage(construit), _horodatage(installe)

    if front_construit and front_installe and front_construit == front_installe:
        return True, f"L'installation correspond a ce build ({_date(ts_installe)})."
    if not front_construit or not front_installe:
        if ts_installe and ts_construit and ts_installe >= ts_construit:
            return True, f"L'installation est au moins aussi recente ({_date(ts_installe)})."
    return False, (
        f"installee : {_date(ts_installe)}   |   construite a l'instant : {_date(ts_construit)}"
    )


def main() -> int:
    construit = ROOT / "AnimeSama"
    if not (construit / _RELATIF_EXE).is_file():
        print("   (pas de dossier AnimeSama\\ a comparer)")
        return 0

    installe = chemin_installe()
    if installe is None:
        print("   Aucune installation detectee : le dossier AnimeSama\\ est la seule copie.")
        return 0

    identiques, message = comparer(construit, installe)
    if identiques:
        print(f"   {message}")
        return 0

    print("")
    print("   ############################################################")
    print("   #  ATTENTION : l'application INSTALLEE n'est pas ce build.  #")
    print("   ############################################################")
    print(f"   {installe}")
    print(f"   {message}")
    print("   Le raccourci du Bureau et du menu Demarrer lancent CELLE-LA.")
    print("   -> Lance AnimeSama-Setup.exe pour installer ce build,")
    print("      ou lance directement AnimeSama\\AnimeSama.exe pour tester sans installer.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
