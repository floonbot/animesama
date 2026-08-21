from engine.download import _helpers as h


def test_normaliser_episodes_from_single_ep():
    out = h.normaliser_episodes({"ep": {"nom": "X", "saison": 2, "episode": 5}})
    assert len(out) == 1 and out[0]["saison"] == 2 and out[0]["episode"] == 5

def test_normaliser_episodes_defaults():
    out = h.normaliser_episodes({"episodes": [{"titre": "T"}]})
    assert out[0]["saison"] == 1 and out[0]["episode"] == 0 and out[0]["titre"] == "T"

def test_normaliser_episodes_titre_inherited():
    out = h.normaliser_episodes({"episodes": [{"titre": "Ref"}, {}]})
    assert out[1]["titre"] == "Ref"

def test_normaliser_episodes_empty():
    assert h.normaliser_episodes({}) == []
    assert h.normaliser_episodes({"episodes": ["notadict"]}) == []

def test_espace_disque_suffisant_true(tmp_path):
    assert h.espace_disque_suffisant(str(tmp_path), minimum_mb=1) is True

def test_espace_disque_suffisant_false_when_huge_min(tmp_path):
    assert h.espace_disque_suffisant(str(tmp_path), minimum_mb=10**12) is False

def test_espace_disque_nonexistent_walks_up(tmp_path):
    assert h.espace_disque_suffisant(str(tmp_path / "pas" / "la"), minimum_mb=1) is True

def test_fichier_existe_found_for_large_file(tmp_path):
    from engine.config.settings import VIDEO_EXTENSIONS
    ext = list(VIDEO_EXTENSIONS)[0]
    f = tmp_path / ("film" + ext)
    with open(f, "wb") as fh:
        fh.truncate(h.TAILLE_MIN_FICHIER + 1)
    assert h.fichier_existe(str(tmp_path), "film") == str(f)

def test_fichier_existe_none_for_small_file(tmp_path):
    from engine.config.settings import VIDEO_EXTENSIONS
    ext = list(VIDEO_EXTENSIONS)[0]
    (tmp_path / ("petit" + ext)).write_bytes(b"x")
    assert h.fichier_existe(str(tmp_path), "petit") is None

def test_fichier_existe_none_when_dir_absent(tmp_path):
    assert h.fichier_existe(str(tmp_path / "nope"), "film") is None

def test_fichier_existe_none_when_interrupted_tmp_dir_present(tmp_path):
    from engine.config.settings import VIDEO_EXTENSIONS
    ext = list(VIDEO_EXTENSIONS)[0]
    f = tmp_path / ("film" + ext)
    with open(f, "wb") as fh:
        fh.truncate(h.TAILLE_MIN_FICHIER + 1)
    (tmp_path / "_tmp_film").mkdir()
    assert h.fichier_existe(str(tmp_path), "film") is None

def test_fichier_existe_found_when_unrelated_tmp_dir_present(tmp_path):
    from engine.config.settings import VIDEO_EXTENSIONS
    ext = list(VIDEO_EXTENSIONS)[0]
    f = tmp_path / ("film" + ext)
    with open(f, "wb") as fh:
        fh.truncate(h.TAILLE_MIN_FICHIER + 1)
    (tmp_path / "_tmp_autre").mkdir()
    assert h.fichier_existe(str(tmp_path), "film") == str(f)

def test_skip_existants_actif_returns_bool():
    assert isinstance(h.skip_existants_actif(), bool)
