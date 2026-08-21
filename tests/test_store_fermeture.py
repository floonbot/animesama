"""D7 (seconde passe) — le jumeau du ResourceWarning corrige sur DiskCache.

Le brief designait `disk_cache.py:49`. Le correctif y a bien ete pose (close()
+ __del__), mais `DownloadStore` ouvre sa propre connexion SQLite au meme
patron et n'avait, lui, aucun filet : `close()` existe, rien ne l'appelle si
l'instance est simplement laissee au ramasse-miettes.

Mesure qui l'etablit :

    PYTHONTRACEMALLOC=30 py -3 -m pytest -W default -p no:randomly \
        -k "cache or disk or store or history or episode"

Le « Object allocated at » remonte a engine/download/store.py:48, jamais a
disk_cache.py. Les tests nommes dans l'avertissement ne sont que ceux ou le GC
est passe : l'avertissement est non levable, il n'accuse pas le coupable.

On n'observe pas l'avertissement lui-meme — il ne se declenche qu'a la
finalisation, dont l'instant n'est pas garanti. On observe l'etat de la
connexion, qui l'est.
"""

import gc
import sqlite3
import weakref

import pytest

from engine.download.store import DownloadStore


def test_le_ramasse_miettes_ferme_la_connexion(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    conn = s._conn          # on garde la connexion, pas le magasin
    temoin = weakref.ref(s)

    del s
    gc.collect()

    # Sans quoi le test passerait pour la mauvaise raison.
    assert temoin() is None, "le magasin n'a pas ete collecte"

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_close_reste_idempotent(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    s.close()
    s.close()
