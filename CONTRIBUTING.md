# Contribuer

Merci de l'intérêt. Autant être clair d'entrée sur ce qui est possible et ce qui ne l'est
pas.

## Contributions de code : pas pour l'instant

Ce dépôt ne porte **aucune licence** — le droit d'auteur par défaut s'applique. Sans
licence, rien n'encadre ce qu'une pull request cède ni ce que le projet peut en faire :
accepter du code dans ces conditions serait flou pour toi comme pour moi. **Les pull
requests ne sont donc pas fusionnées.**

Ça pourra changer. En attendant, la meilleure contribution est un bon rapport.

## Rapports de bug : bienvenus

Ouvre une [issue](../../issues/new/choose). L'application expose tout ce qu'il faut pour
en écrire un utile :

- **`GET /api/health`** — version, moteurs détectés, navigateur, disque, uptime. Colle-le
  entier : il ne contient aucun secret, l'expurgation est intégrée.
- **`GET /api/logs`** — les dernières lignes du journal en mémoire, corrélées par
  identifiant de tâche `[id]`. URLs expurgées, cookies jamais journalisés.
- La **page Diagnostic** de l'application réunit les deux, avec un bouton d'export.

Précise aussi ton OS, et si le problème vient de l'installeur ou de l'application.

## Compiler chez toi

Prérequis : **Python 3.13+** et **Node.js**.

```bash
git clone https://github.com/floonbot/animesama.git
cd animesama
```

Un seul script installe les dépendances Python, Chromium et les binaires de
téléchargement :

```bat
packaging\install.bat
```
```bash
chmod +x packaging/install.sh && ./packaging/install.sh
```

Puis, pour construire l'exécutable et l'installeur :

```bat
BUILD.bat
```

Le détail des étapes est dans le [README](README.md).

## Contrôles

Les trois commandes que la CI fait tourner :

```bash
ruff check .        # lint (E, F, I, B, UP, ASYNC ; ligne 100 ; cible py313)
mypy .              # typage
pytest -q           # la suite complète
```

Deux choses à savoir sur la suite :

- L'ordre des tests est **aléatoire** (`pytest-randomly`). C'est volontaire : une
  pollution d'état entre tests a déjà existé sur ce projet. Si un test échoue seulement
  dans un certain ordre, c'est un vrai bug, pas une nuisance — relance avec
  `pytest -q -p no:randomly` pour comparer, mais corrige la cause.
- Les tests marqués `integration` (vrai ffmpeg, vrais sous-processus) sont **désélectionnés
  par défaut**. Pour les lancer : `pytest -m integration`.

Les tests de bout en bout (Playwright) ont besoin d'un serveur lancé :

```bash
npm install
npx playwright test
```

## Style

Le code, les commentaires et les messages de commit sont **en français** — c'est la
convention du dépôt, autant la suivre. Les commentaires expliquent *pourquoi*, pas
*quoi* : le code dit déjà ce qu'il fait.
