"""Regression: yt-dlp's merge/fixup temp file `<nom>.temp.<ext>` (produced by
yt-dlp's `prepend_extension(filename, 'temp')`) ends in a video extension, so
`_nettoyer_fragments` used to keep it and `_trouver_fichier_final` used to serve
it as the finished video. It must now be cleaned up and never returned, while a
legitimate single-format `<nom>.f137.mp4` output stays untouched.
"""

import engine.download.methods.ytdlp_engine as ytdlp_engine


def test_nettoyer_fragments_removes_merge_temp_keeps_final(tmp_path):
    nom = "Youjo Senki - Film - E001 VOSTFR"
    final = tmp_path / (nom + ".mp4")
    final.write_bytes(b"video")
    (tmp_path / (nom + ".temp.mp4")).write_bytes(b"junk")
    (tmp_path / (nom + ".temp.mkv")).write_bytes(b"junk")

    n = ytdlp_engine._nettoyer_fragments(str(tmp_path), nom)

    assert n == 2
    assert final.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [nom + ".mp4"]


def test_nettoyer_fragments_keeps_single_format_output(tmp_path):
    (tmp_path / "ep.f137.mp4").write_bytes(b"video")

    n = ytdlp_engine._nettoyer_fragments(str(tmp_path), "ep")

    assert n == 0
    assert (tmp_path / "ep.f137.mp4").exists()


def test_trouver_fichier_final_ignores_merge_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 1)
    (tmp_path / "ep.temp.mp4").write_bytes(b"y" * 100)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep") is None


def test_trouver_fichier_final_still_accepts_format_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 1)
    cible = tmp_path / "ep.f137.mp4"
    cible.write_bytes(b"y" * 100)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep") == str(cible)
