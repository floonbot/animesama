from engine.download.methods import nm3u8dl


def test_nettoyer_residus_mux_removes_muxed_orphan(tmp_path):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"final")
    orphan = tmp_path / "ep.MUX.mp4"
    orphan.write_bytes(b"muxed")

    removed = nm3u8dl._nettoyer_residus_mux(str(tmp_path), "ep")

    assert removed == 1
    assert not orphan.exists()
    assert final.exists()


def test_nettoyer_residus_mux_removes_multiple_extensions(tmp_path):
    (tmp_path / "ep.MUX.mp4").write_bytes(b"a")
    (tmp_path / "ep.MUX.mkv").write_bytes(b"b")

    removed = nm3u8dl._nettoyer_residus_mux(str(tmp_path), "ep")

    assert removed == 2
    assert not (tmp_path / "ep.MUX.mp4").exists()
    assert not (tmp_path / "ep.MUX.mkv").exists()


def test_nettoyer_residus_mux_noop_when_absent(tmp_path):
    (tmp_path / "ep.mp4").write_bytes(b"final")

    assert nm3u8dl._nettoyer_residus_mux(str(tmp_path), "ep") == 0
    assert (tmp_path / "ep.mp4").exists()


def test_nettoyer_residus_mux_swallows_remove_oserror(tmp_path, monkeypatch):
    orphan = tmp_path / "ep.MUX.mp4"
    orphan.write_bytes(b"muxed")

    def _boom(_p):
        raise OSError("locked")

    monkeypatch.setattr(nm3u8dl.os, "remove", _boom)

    assert nm3u8dl._nettoyer_residus_mux(str(tmp_path), "ep") == 0


class _Proc:
    def __init__(self):
        self.stdout = None
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


def test_download_success_cleans_mux_residual(tmp_path, monkeypatch):
    final = tmp_path / "ep.mp4"
    final.write_bytes(b"z" * 64)
    orphan = tmp_path / "ep.MUX.mp4"
    orphan.write_bytes(b"muxed")

    proc = _Proc()
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_lire_stdout_avec_timeout", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_spawn_proc_watchdog", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    monkeypatch.setattr(nm3u8dl, "_trouver_fichier_final", lambda d, n, avant=None: str(final))

    res = nm3u8dl.nm3u8dl_download("http://host/x.m3u8", str(tmp_path), "ep")

    assert res == str(final)
    assert final.exists()
    assert not orphan.exists()
