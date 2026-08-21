"""Regression: ytdlp_engine._trouver_fichier_final must not propagate an OSError
from a TOCTOU getsize in its primary (exact-name) branch. Previously only the
listdir fallback wrapped getsize in try/except; a file vanishing between
os.path.exists and os.path.getsize turned a successful download into a reported
failure. Mirrors the nm3u8dl twin's getsize-OSError guard.
"""

import engine.download.methods.ytdlp_engine as ytdlp_engine


def test_trouver_fichier_final_getsize_oserror_continues(monkeypatch, tmp_path):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 1)
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 100)

    def _getsize(_p):
        raise OSError("stat failed")

    monkeypatch.setattr(ytdlp_engine.os.path, "getsize", _getsize)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep") is None
