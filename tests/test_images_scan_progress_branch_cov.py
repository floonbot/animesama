"""Regression: two correctness gaps in the scan (CBZ) path.
1. scan_download skipped an empty chapter without incrementing `faits`, so the
   progress could never reach 100 % when any chapter yielded no pages.
2. _ecrire_cbz_chapitre did int(p["page"]) unguarded; a present-but-non-numeric
   page value raised ValueError and aborted the whole scan.
"""

import os
import zipfile

import engine.download.methods.images as images_mod


def test_empty_chapter_advances_progress_to_100(monkeypatch, tmp_path):
    import engine.scraping.scan as scan_mod

    monkeypatch.setattr(scan_mod, "get_pages_sync", lambda *a, **k: [])
    seen = []
    images_mod.scan_download(
        "Work", "vf", ["1", "2"], str(tmp_path),
        on_progress=lambda pct, msg: seen.append(pct),
    )
    assert seen
    assert seen[-1] == 100


def test_non_numeric_page_does_not_abort_chapter(monkeypatch, tmp_path):
    monkeypatch.setattr(images_mod, "_telecharger_image", lambda s, u, c: (b"x", ".jpg"))
    cbz = str(tmp_path / "Chapitre 1.cbz")
    images_mod._ecrire_cbz_chapitre(
        None, [{"page": "notanumber", "url": "u"}], "1", cbz, 0, 1, None, None, {},
    )
    assert os.path.exists(cbz)
    with zipfile.ZipFile(cbz) as zf:
        assert zf.namelist() == ["001.jpg"]
