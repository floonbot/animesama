"""Mettre a l'ecart un fichier de configuration illisible, au lieu de l'ecraser.

Un JSON tronque — coupure pendant l'ecriture, disque plein — se lit comme « pas
de reglages ». Les appelants repartaient donc des valeurs par defaut, et la
sauvegarde suivante ecrasait le fichier : les dossiers de telechargement, la
qualite, la liste des profils disparaissaient sans laisser de trace. Or le
contenu d'origine est le plus souvent recuperable a la main.

Meme convention de nom que DownloadStore pour la base SQLite (« .corrupt »),
pour que tout ce qui est mis a l'ecart dans data/ se ressemble.

Une erreur d'E/S n'est pas une corruption : un fichier verrouille ou un droit
manquant redeviendra lisible. Seul un contenu invalide passe par ici.
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("engine.config.quarantaine")

MAX_ECARTS = 20


def _cible_libre(chemin: Path) -> Path | None:
    cible = chemin.with_name(chemin.name + ".corrupt")
    n = 1
    while cible.exists():
        if n > MAX_ECARTS:
            return None
        cible = chemin.with_name(f"{chemin.name}.corrupt-{n}")
        n += 1
    return cible


def mettre_a_lecart(chemin: Path, motif: str) -> Path | None:
    cible = _cible_libre(chemin)
    if cible is None:
        log.error(
            "%s est illisible (%s) et %d copies sont deja mises a l'ecart — "
            "le fichier est laisse en place.\n"
            "→ Fais le menage dans « %s » puis relance l'application.",
            chemin.name, motif, MAX_ECARTS, chemin.parent,
        )
        return None
    try:
        os.replace(str(chemin), str(cible))
    except OSError as e:
        log.error(
            "%s est illisible (%s) et n'a pas pu etre mis de cote (%s) — "
            "les valeurs par defaut s'appliquent, mais toute sauvegarde "
            "ecrasera ce fichier.", chemin.name, motif, e,
        )
        return None
    log.error(
        "%s etait illisible (%s). Le fichier a ete conserve sous « %s » et "
        "les valeurs par defaut s'appliquent.\n"
        "→ Son contenu est peut-etre recuperable a la main ; rien n'a ete efface.",
        chemin.name, motif, cible.name,
    )
    return cible
