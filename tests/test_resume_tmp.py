import os
import time

import engine.config.settings as settings
from engine.download.methods import nm3u8dl


def test_purge_stale_tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_downloads_dir", lambda: tmp_path)

    anime = tmp_path / "Anime"
    old = anime / "_tmp_ep_old"
    fresh = anime / "_tmp_ep_fresh"
    real = anime / "Saison 1"
    for p in (old, fresh, real):
        p.mkdir(parents=True)

    old_ts = time.time() - 10 * 24 * 3600
    os.utime(old, (old_ts, old_ts))

    removed = nm3u8dl.purge_stale_tmp_dirs(max_age_s=7 * 24 * 3600)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
    assert real.exists()

def test_purge_handles_missing_root(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(settings, "get_downloads_dir", lambda: missing)
    assert nm3u8dl.purge_stale_tmp_dirs() == 0
