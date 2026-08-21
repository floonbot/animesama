"""Regression : la reponse d'erreur de l'API ne doit pas devenir un chapitre.

Fait observe le 17/08/2026, sonde sur l'API reelle :

    GET /s2/scans/get_nb_chap_et_img.php?oeuvre=Dragon+Ball+Super&lang=vf
    -> {"error":"Oeuvre 'Dragon Ball Super' not found"}

`get_scan_info_sync` prenait *chaque cle* de la reponse pour un numero de
chapitre. La cle « error » devenait donc un chapitre, et la fonction rendait
`ok=True` avec `total=1`. Cote interface, la modale affichait « Commencer —
Ch. error » et une puce « error » : le garde-fou du front
(`!_info.ok || !chapitres.length`) ne pouvait rien, les deux conditions etaient
satisfaites.

Ce que ces tests verrouillent, et qui n'est pas evident : le filtre ne peut pas
etre « seulement des numeros ». L'API sert aussi des chapitres speciaux nommes,
et `test_scan_info_success` en garde un (`bonus`) volontairement. La regle
retenue accepte donc deux formes — un numero, ou un nombre de pages positif — ce
qui laisse passer les speciaux et rejette « error », dont la valeur est une
phrase.

Non teste ici parce que ce n'est pas un defaut de l'application : Naruto declare
`creerListe(1,700)` dans sa page mais l'API l'ignore et
/s2/scans/Naruto/1/1.jpg rend 404. Se rabattre sur la page listerait 700
chapitres injoignables. Voir le commentaire de scan.py.
"""

import json

import pytest

from engine.scraping import scan as scan_mod


class _DisqueMuet:
    def get(self, key):
        return None

    def set(self, key, value):
        pass


@pytest.fixture(autouse=True)
def _isoler(monkeypatch):
    with scan_mod._scan_info_lock:
        avant = dict(scan_mod._scan_info_cache)
        scan_mod._scan_info_cache.clear()
    monkeypatch.setattr(scan_mod, "_scan_disk", _DisqueMuet())
    monkeypatch.setattr(scan_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        scan_mod, "_fetch_text",
        lambda *a, **k: (200, '<h3 id="titreOeuvre">Dragon Ball Super</h3>'
                              '<select id="selectChapitres"></select>'),
    )
    yield
    with scan_mod._scan_info_lock:
        scan_mod._scan_info_cache.clear()
        scan_mod._scan_info_cache.update(avant)


def _api(monkeypatch, charge):
    monkeypatch.setattr(scan_mod, "_fetch_api_retry", lambda *a, **k: json.dumps(charge))


def test_l_erreur_de_l_api_ne_devient_pas_un_chapitre(monkeypatch):
    _api(monkeypatch, {"error": "Oeuvre 'Dragon Ball Super' not found"})

    out = scan_mod.get_scan_info_sync("dragon-ball-super", "vf")

    assert out["ok"] is False
    assert out["chapitres"] == []
    assert "error" not in [c["num"] for c in out["chapitres"]]


def test_le_message_de_l_api_est_remonte_tel_quel(monkeypatch):
    """« aucun scan disponible » sans raison laisse chercher dans le vide."""
    _api(monkeypatch, {"error": "Oeuvre 'Dragon Ball Super' not found"})

    out = scan_mod.get_scan_info_sync("dragon-ball-super", "vf")

    assert out["error"] == "Oeuvre 'Dragon Ball Super' not found"
    assert out["oeuvre"] == "Dragon Ball Super"
    assert out["lang"] == "vf"


def test_une_erreur_melee_a_de_vrais_chapitres_est_la_seule_ecartee(monkeypatch):
    _api(monkeypatch, {"1": 20, "error": "partiel", "2": 18, "12.5": 8})

    out = scan_mod.get_scan_info_sync("dragon-ball-super", "vf")

    assert out["ok"] is True
    assert [c["num"] for c in out["chapitres"]] == ["1", "2", "12.5"]


def test_un_chapitre_special_nomme_survit_au_filtre(monkeypatch):
    """Le filtre ne peut pas etre « seulement des chiffres » : un special
    annonce un nombre de pages, et c'est ce qui le distingue d'une erreur."""
    _api(monkeypatch, {"1": 20, "bonus": 12, "error": "ignore"})

    out = scan_mod.get_scan_info_sync("dragon-ball-super", "vf")

    assert out["ok"] is True
    assert sorted(c["num"] for c in out["chapitres"]) == ["1", "bonus"]


def test_un_echec_n_est_jamais_mis_en_cache(monkeypatch):
    """L'API peut apprendre l'oeuvre plus tard ; figer l'echec six heures sur
    disque rendrait la reparation invisible jusqu'au lendemain."""
    _api(monkeypatch, {"error": "not found"})
    premier = scan_mod.get_scan_info_sync("dragon-ball-super", "vf")
    assert premier["ok"] is False

    _api(monkeypatch, {"1": 20})
    second = scan_mod.get_scan_info_sync("dragon-ball-super", "vf")

    assert second["ok"] is True
    assert [c["num"] for c in second["chapitres"]] == ["1"]


def test_une_reponse_vide_est_un_echec_pas_un_succes_a_zero_chapitre(monkeypatch):
    """ok=True avec zero chapitre ouvrait une modale vide au lieu d'un message."""
    _api(monkeypatch, {})

    out = scan_mod.get_scan_info_sync("dragon-ball-super", "vf")

    assert out["ok"] is False
    assert out["error"]
