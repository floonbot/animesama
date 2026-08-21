# type: ignore
import glob
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

REQUIRED_BINARIES = ("N_m3u8DL-RE.exe", "yt-dlp.exe", "ffmpeg.exe")
OPTIONAL_BINARIES = ("aria2c.exe", "ffprobe.exe")


def _bin_datas():
    out = []
    bin_dir = os.path.join(ROOT, "bin")
    manquants = []
    for name in REQUIRED_BINARIES:
        chemin = os.path.join(bin_dir, name)
        if os.path.exists(chemin):
            out.append((chemin, "bin"))
        else:
            manquants.append(name)
    if manquants:
        raise SystemExit(
            "anime_sama.spec: binaires manquants dans bin/ : "
            + ", ".join(manquants)
            + " -> lance install.bat avant le build."
        )
    for name in OPTIONAL_BINARIES:
        chemin = os.path.join(bin_dir, name)
        if os.path.exists(chemin):
            out.append((chemin, "bin"))
    return out


def _browsers_root():
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root:
        return root
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(local, "ms-playwright")


def _headless_only():
    return os.environ.get("ANIMESAMA_HEADLESS_ONLY", "").strip().lower() in ("1", "true", "yes", "on")


def _chromium_browser_dirs():
    import playwright
    pw_dir = os.path.dirname(playwright.__file__)
    browsers_json = os.path.join(pw_dir, "driver", "package", "browsers.json")
    with open(browsers_json, encoding="utf-8") as f:
        data = json.load(f)
    headless_only = _headless_only()
    folders = []
    for b in data.get("browsers", []):
        name = b.get("name")
        if name not in ("chromium", "chromium-headless-shell"):
            continue
        if not b.get("installByDefault", False):
            continue
        if headless_only and name == "chromium":
            continue
        folders.append(name.replace("-", "_") + "-" + str(b.get("revision")))
    return folders


def _chromium_datas():
    root = _browsers_root()
    folders = _chromium_browser_dirs()
    present = [(f, os.path.join(root, f)) for f in folders if os.path.isdir(os.path.join(root, f))]
    if not present:
        raise SystemExit(
            f"anime_sama.spec: Chromium introuvable dans {root} (attendu : {folders}). "
            "Lance `python -m playwright install chromium` avant le build."
        )
    out = []
    for folder, chromium_dir in present:
        base = "ms-playwright/" + folder
        for chemin in glob.glob(os.path.join(chromium_dir, "**", "*"), recursive=True):
            if os.path.isfile(chemin):
                rel_dir = os.path.dirname(os.path.relpath(chemin, chromium_dir))
                dest = os.path.join(base, rel_dir) if rel_dir else base
                out.append((chemin, dest))
    return out


_hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("engine")
    + collect_submodules("web")
    + collect_submodules("playwright")
    + ["webview", "anyio", "click", "h11", "websockets",
       "playwright_stealth", "greenlet", "pyee"]
)

_STATIC = os.path.join(ROOT, "web", "static")
_datas = []
for _chemin in glob.glob(os.path.join(_STATIC, "**", "*"), recursive=True):
    if not os.path.isfile(_chemin):
        continue
    _rel = os.path.relpath(_chemin, _STATIC)
    if _rel.endswith(".map") or _rel.endswith("metafile.json"):
        continue
    if _rel.split(os.sep)[0] == "js":
        continue
    _rel_dir = os.path.dirname(_rel)
    _datas.append((_chemin, os.path.join("web/static", _rel_dir) if _rel_dir else "web/static"))

_datas += [(os.path.join(ROOT, "engine", "download", "extractor", "js_hooks.js"),
            "engine/download/extractor")]
_datas += collect_data_files("playwright")
_datas += collect_data_files("playwright_stealth")
_datas += _bin_datas()
_datas += _chromium_datas()

a = Analysis(
    [os.path.join(ROOT, "desktop.py")],
    pathex=[ROOT],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    runtime_hooks=[os.path.join(ROOT, "packaging", "rthook_playwright.py")],
    excludes=["tkinter", "numpy", "mypy", "ast_serialize", "tzdata"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnimeSama",
    console=False,
    icon=os.path.join(ROOT, "packaging", "animesama.ico"),
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="AnimeSama",
)
