import engine.library.scanner as scanner_mod
from engine.config.settings import VIDEO_EXTENSIONS


def test_scan_un_dossier_counts_webm_episode(tmp_path):
    saison = tmp_path / "Naruto" / "Saison 01"
    saison.mkdir(parents=True)
    (saison / "Naruto S01E05 VOSTFR.webm").write_bytes(b"x" * 32)
    (saison / "Naruto S01E06 VOSTFR.mp4").write_bytes(b"x" * 32)

    animes, _ = scanner_mod._scan_un_dossier(tmp_path)

    assert "Naruto" in animes
    episodes = animes["Naruto"]["saisons"][0]["episodes"]
    noms = {e["nom"] for e in episodes}
    assert "Naruto S01E05 VOSTFR" in noms
    assert "Naruto S01E06 VOSTFR" in noms


def test_scan_un_dossier_video_extensions_include_webm():
    assert ".webm" in VIDEO_EXTENSIONS
