from engine.library.updates import langue_locale


def test_langue_locale_extrait_langue_dominante():
    saisons = [
        {"episodes": [
            {"nom": "Anime - S01E001 VOSTFR"},
            {"nom": "Anime - S01E002 VOSTFR"},
            {"nom": "Anime - S01E003 VF"},
        ]},
    ]
    assert langue_locale(saisons) == "VOSTFR"


def test_langue_locale_vide_si_aucune_langue():
    saisons = [{"episodes": [{"nom": "Anime - S01E005"}]}]
    assert langue_locale(saisons) == ""


def test_langue_locale_ancree_en_fin_pas_dans_le_titre():
    saisons = [{"episodes": [{"nom": "VA-11 Hall-A - S01E001"}]}]
    assert langue_locale(saisons) == ""


def test_langue_locale_vf_pas_confondu_avec_vf1():
    saisons = [{"episodes": [
        {"nom": "Anime - S01E001 VF1"},
        {"nom": "Anime - S01E002 VF1"},
    ]}]
    assert langue_locale(saisons) == "VF1"
