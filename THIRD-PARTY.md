# Composants tiers

Ce fichier recense ce que le dépôt et le paquet distribué embarquent sans en être
l'auteur. Il vaut pour le dépôt **et** pour toute release de `AnimeSama-Setup.exe` : les
obligations ci-dessous suivent le binaire, pas le code source.

---

## Outils de téléchargement embarqués dans l'installeur

`packaging/install.bat` les télécharge dans `bin/`, `packaging/anime_sama.spec` les
embarque dans le paquet, et `packaging/installer.iss` met le paquet dans l'installeur.
Ils ne sont **pas** dans le dépôt : `bin/` est ignoré par Git.

| Outil | Rôle | Licence | Source |
|---|---|---|---|
| **FFmpeg** (compilation `win64-gpl`) | remux et concaténation des segments | **GPL v2 ou ultérieure** — voir ci-dessous | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) · [ffmpeg.org](https://ffmpeg.org/) |
| **yt-dlp** | extraction de secours | Unlicense | [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| **N_m3u8DL-RE** | téléchargeur HLS principal | MIT | [nilaoda/N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) |
| **aria2** (`aria2c`) | accélérateur optionnel | GPL v2 ou ultérieure | [aria2/aria2](https://github.com/aria2/aria2) |

### FFmpeg — obligations GPL

La compilation utilisée est produite avec `--enable-gpl`, ce qui place l'ensemble de
FFmpeg sous **GPL v2 ou ultérieure**. Distribuer le binaire impose donc :

- de **fournir le code source correspondant** à la version distribuée, ou une offre écrite
  de le fournir ;
- de **documenter la ligne de configure** ayant servi à la compilation ;
- de **mentionner explicitement** l'usage de FFmpeg, et d'en attribuer correctement les
  auteurs ;
- de ne pas restreindre la rétro-ingénierie ni renommer les bibliothèques de façon
  obfusquée.

Les sources et la configuration exacte de chaque compilation sont publiées par
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), dont chaque release indique le
commit FFmpeg et le script de build utilisés. Le détail des licences est sur
[ffmpeg.org/legal.html](https://ffmpeg.org/legal.html).

**FFmpeg est appelé comme processus séparé** (`subprocess`), avec `-c copy` uniquement —
aucun encodage, aucun filtre, aucune liaison à ses bibliothèques. La GPL de FFmpeg porte
sur le binaire redistribué, pas sur le code Python de cette application.

---

## Composant d'affichage

| Composant | Licence | Source |
|---|---|---|
| **Microsoft Edge WebView2 Runtime** | Microsoft Software License Terms | [developer.microsoft.com/microsoft-edge/webview2](https://developer.microsoft.com/microsoft-edge/webview2/) |

Le dépôt ne contient aucun binaire Microsoft. `packaging/install.bat` télécharge le
*bootstrapper Evergreen* (~2 Mo) depuis le
[permalien officiel](https://go.microsoft.com/fwlink/p/?LinkId=2124703) au moment du build ;
l'installeur le lance uniquement si le runtime est absent de la machine, et il va ensuite
chercher le runtime chez Microsoft. Cette façon de faire est celle que
[Microsoft documente](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

---

## Navigateur d'extraction

| Composant | Licence | Source |
|---|---|---|
| **Chromium** (via Playwright) | BSD 3-Clause | [playwright.dev](https://playwright.dev/) · [chromium.org](https://www.chromium.org/) |

Installé par `playwright install chromium` et embarqué dans le paquet.

---

## Polices

Quatre familles sous **SIL Open Font License 1.1**, dans `web/static/fonts/`. Notices et
texte intégral : [`web/static/fonts/LICENSES.md`](web/static/fonts/LICENSES.md).

---

## Dépendances Python

Épinglées dans `requirements/constraints.txt`. Les principales — FastAPI, Starlette,
Uvicorn, Pydantic (MIT / BSD), Playwright, requests, cryptography (Apache 2.0),
BeautifulSoup, lxml, httpx, keyring, Pillow, psutil — sont sous licences permissives.

**PyInstaller** est sous GPL 2.0 assortie d'une exception explicite : les exécutables
qu'il produit *« can be shipped with whatever license you want »*
([pyinstaller.org](https://pyinstaller.org/en/stable/license.html)). Empaqueter cette
application ne la place donc pas sous GPL.

---

## Visuels

Les images de `web/static/img/`, `web/static/favicon.png`, `packaging/animesama.ico` et
l'écran d'attente encodé dans `desktop.py` sont des **œuvres dérivées de personnages
tiers**, générées localement. Elles sont fournies pour l'usage de cette application
seulement et ne sont couvertes par aucune licence de réutilisation.

---

## Site source

L'application ne redistribue aucun contenu et n'inclut aucune donnée provenant du site
qu'elle interroge. Elle n'est affiliée ni à ce site ni à aucun ayant droit.
