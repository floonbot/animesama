"""Regression: ytdlp_engine._trouver_fichier_final prefix fallback must not
cross episode boundaries (S01E100 is a literal prefix of S01E1000), and the
`qualite` setting must be coerced to str before the command is built.
"""

import threading

from engine.download.methods import ytdlp_engine


def test_trouver_fichier_final_does_not_match_longer_episode(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 50)
    (tmp_path / "One Piece - S01E1000.mp4").write_bytes(b"y" * 100)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "One Piece - S01E100") is None


def test_trouver_fichier_final_accepts_separator_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 50)
    cible = tmp_path / "ep.f137.mp4"
    cible.write_bytes(b"y" * 100)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep") == str(cible)


def test_trouver_fichier_final_exact_match_preferred(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 50)
    exact = tmp_path / "ep.mp4"
    exact.write_bytes(b"y" * 100)

    assert ytdlp_engine._trouver_fichier_final(str(tmp_path), "ep") == str(exact)


class _Iter:
    def __init__(self, items):
        self._items = list(items)
        self._i = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._items):
            raise StopIteration
        item = self._items[self._i]
        self._i += 1
        return item

    def close(self):
        return None


class _Proc:
    def __init__(self, stdout_lines, returncode=0):
        self.returncode = returncode
        self.pid = 4321
        self.stdout = _Iter(stdout_lines)
        self.stderr = None

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        return None

    def terminate(self):
        return None


def test_ytdlp_download_coerces_int_qualite(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"x" * 4096)

    monkeypatch.setattr(
        ytdlp_engine.subprocess, "Popen",
        lambda cmd, *a, **k: _Proc(["[download] 100% of 100.00MiB"], returncode=0),
    )
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n: str(final))
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": 1080})

    res = ytdlp_engine.ytdlp_download("http://host.example/video", str(tmp_path), "ep")
    assert res == str(final)
