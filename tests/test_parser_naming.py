from engine.scraping.parser import nettoyer_titre, nom_fichier


def test_nettoyer_titre_strips_season_suffix():
    assert nettoyer_titre("One Piece Saison 2") == "One Piece"

def test_nettoyer_titre_removes_fs_invalid_chars():
    out = nettoyer_titre('Na/ru:to?<>|')
    assert "/" not in out and ":" not in out and "?" not in out

def test_nettoyer_titre_empty_defaults():
    assert nettoyer_titre("") == "Anime"

def test_nettoyer_titre_caps_length():
    assert len(nettoyer_titre("x" * 300)) <= 100

def test_nom_fichier_format():
    assert nom_fichier("Naruto", 1, 5, "VOSTFR") == "Naruto - S01E005 VOSTFR"

def test_nom_fichier_no_duplicate_lang():
    out = nom_fichier("Naruto VOSTFR", 1, 5, "VOSTFR")
    assert out.count("VOSTFR") == 1

def test_nom_fichier_handles_bad_numbers():
    out = nom_fichier("X", "bad", None)
    assert "S01E000" in out
