"""Ecrit web/static/build-info.json : l'horodatage et l'empreinte du paquet.

Appele par build_exe.bat entre le bundle esbuild et PyInstaller, donc apres que
web/static/dist existe. Le fichier atterrit dans web/static, que la spec embarque
telle quelle : le paquet installe sait ainsi quand il a ete construit, ce que le
depot seul ne peut pas dire.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.version import APP_VERSION, TAMPON_NOM  # noqa: E402

STATIC = ROOT / "web" / "static"


def _fichiers_front() -> list[Path]:
    fichiers = []
    index = STATIC / "index.html"
    if index.is_file():
        fichiers.append(index)
    dist = STATIC / "dist"
    if dist.is_dir():
        fichiers += [
            f for f in dist.rglob("*")
            if f.is_file() and f.suffix not in (".map",) and f.name != "metafile.json"
        ]
    return sorted(fichiers)


def empreinte_front() -> str:
    h = hashlib.sha256()
    for f in _fichiers_front():
        h.update(f.relative_to(STATIC).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:12]


def _git(*args: str):
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def revision_git() -> str:
    """SHA de HEAD, suffixe par l'etat de l'arbre de travail.

    Le SHA nu mentait : un paquet construit sur un arbre modifie annoncait le
    commit precedent, alors que le tampon existe justement pour savoir quel code
    tourne. `-inconnu` couvre le cas ou `git status` echoue — ne pas savoir n'est
    pas la meme chose qu'un arbre propre.
    """
    tete = _git("rev-parse", "--short", "HEAD")
    if tete is None or tete.returncode != 0:
        return ""
    sha = tete.stdout.strip()
    if not sha:
        return ""
    etat = _git("status", "--porcelain", "--untracked-files=normal")
    if etat is None or etat.returncode != 0:
        return f"{sha}-inconnu"
    return f"{sha}-dirty" if etat.stdout.strip() else sha


def construire_tampon(maintenant: float | None = None) -> dict:
    ts = time.time() if maintenant is None else maintenant
    return {
        "version": APP_VERSION,
        "built_at": round(ts, 3),
        "built_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
        "front": empreinte_front(),
        "git": revision_git(),
        # build_exe.bat lance stamp_build.py et PyInstaller avec le meme
        # interpreteur : celui note ici est donc celui que le paquet embarque.
        # `py -3` suit le Python par defaut de la machine, qui n'est pas
        # forcement celui sous lequel la suite de tests passe.
        "python": platform.python_version(),
    }


def main() -> int:
    if not (STATIC / "dist" / "app.js").is_file():
        print("stamp_build: web/static/dist/app.js absent — lance le bundle front d'abord.")
        return 1
    tampon = construire_tampon()
    cible = STATIC / TAMPON_NOM
    try:
        tmp = cible.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(tampon, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, cible)
    except OSError as e:
        print(f"stamp_build: ecriture de {TAMPON_NOM} impossible : {e}")
        return 1
    print(f"stamp_build: {TAMPON_NOM} -> {tampon['version']} "
          f"{tampon['built_at_iso']} front={tampon['front']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
