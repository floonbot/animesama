#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."

echo "  Anime Downloader - Installation (POSIX)"
echo "  ======================================="

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "ERREUR : Python 3 introuvable. Installe-le via ton gestionnaire de paquets."
    exit 1
fi
echo "[1/5] $("$PY" --version)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)' \
    || echo "    ATTENTION : Python 3.13+ requis (pyproject.toml). L'installation continue."

echo "[2/5] Installation des dépendances Python..."
"$PY" -m pip install --upgrade pip
if [ -f requirements/constraints.txt ]; then
    "$PY" -m pip install -r requirements/requirements.txt -c requirements/constraints.txt
else
    "$PY" -m pip install -r requirements/requirements.txt
fi
"$PY" -m pip install Pillow || echo "    Pillow optionnel non installé (jaquettes en taille d'origine)"

# install.bat les installe : sans eux, « python desktop.py » sort sur « pywebview est
# requis » alors que le script d'installation vient d'annoncer avoir tout mis en place.
echo "[3/5] Dépendances de l'application de bureau (pywebview, pyinstaller)..."
"$PY" -m pip install -r requirements/requirements-desktop.txt || {
    echo "    ÉCHEC : pywebview a besoin de dépendances système (GTK ou Qt) sur cette"
    echo "    plateforme. Installe-les puis relance, ou utilise le serveur seul :"
    echo "      $PY -c 'import server; server.start_server()'  puis http://127.0.0.1:7843"
}

echo "[4/5] Installation de Chromium (Playwright)..."
"$PY" -m playwright install chromium
"$PY" -m playwright install-deps chromium 2>/dev/null || true

echo "[5/5] Vérification des outils (dans bin/ ou dans le PATH) :"
mkdir -p bin
for bin in N_m3u8DL-RE yt-dlp ffmpeg aria2c; do
    if [ -x "bin/$bin" ] || command -v "$bin" >/dev/null 2>&1; then
        echo "    [x] $bin"
    else
        echo "    [ ] $bin manquant — place-le dans bin/ ou installe-le (apt/brew)"
        echo "        (N_m3u8DL-RE : depuis ses releases GitHub)"
    fi
done

[ -f .env ] || { printf 'PORT=7843\n' > .env; echo "    .env créé"; }
mkdir -p downloads scans data

echo "  ======================================="
echo "  Installation terminée. Lance : python3 desktop.py"
