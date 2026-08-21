"""C12.a — le module front qui lit l'appartenance aux listes.

Le champ `listes` est arrive apres coup : le cache de session du navigateur et
le cache du serveur peuvent servir des entrees ecrites par la version
precedente. Une entree sans le champ doit valoir « favori », sans quoi
un retour sur la page ferait disparaitre toute la liste.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LISTES = ROOT / "web" / "static" / "js" / "utils" / "listes.js"


def _node(expr: str):
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node absent — le module de listes se verifie aussi en e2e")
    script = (
        f"import * as L from {LISTES.as_uri()!r};\n"
        f"process.stdout.write(JSON.stringify({expr}));\n"
    )
    r = subprocess.run(
        [exe, "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT), timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_entree_sans_champ_listes_reste_un_favori():
    assert _node("L.listesDe({nom: 'X'})") == ["favoris"]
    assert _node("L.dansListe({nom: 'X'}, 'favoris')") is True
    assert _node("L.dansListe({nom: 'X'}, 'watchlist')") is False


def test_champ_listes_vide_ou_invalide_retombe_sur_favoris():
    assert _node("L.listesDe({listes: []})") == ["favoris"]
    assert _node("L.listesDe({listes: 'watchlist'})") == ["favoris"]
    assert _node("L.listesDe(null)") == ["favoris"]


def test_une_seule_liste_presente_ne_rend_aucune_puce():
    animes = "[{listes:['favoris']},{listes:['favoris']}]"
    assert _node(f"L.listesPresentes({animes})") == []


def test_les_puces_suivent_l_ordre_declare_et_portent_leur_compte():
    animes = (
        "[{listes:['watchlist']},"
        " {listes:['favoris','watchlist']},"
        " {listes:['historique']}]"
    )
    assert _node(f"L.listesPresentes({animes}).map(l => [l.id, l.n])") == [
        ["favoris", 1], ["watchlist", 2], ["historique", 1],
    ]


def test_liste_vide_sur_le_compte_n_a_pas_de_puce():
    animes = "[{listes:['favoris']},{listes:['watchlist']}]"
    ids = _node(f"L.listesPresentes({animes}).map(l => l.id)")
    assert "vus" not in ids


def test_filtrer_et_compter_traitent_l_absence_du_champ():
    animes = "[{nom:'A'},{nom:'B',listes:['watchlist']}]"
    assert _node(f"L.filtrerListe({animes}, 'favoris').map(a => a.nom)") == ["A"]
    assert _node(f"L.compter({animes}, 'watchlist')") == 1
