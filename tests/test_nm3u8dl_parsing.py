from engine.download.methods._nm3u8dl_parsing import (
    construire_commande,
    get_thread_count,
    interpreter_ligne,
)


def _cmd(headers=None, settings=None):
    return construire_commande(
        "EXE", "http://h/x.m3u8", "/dossier", "nom", "/tmp",
        headers or {}, settings or {},
    )

def test_get_thread_count_clamps_and_defaults():
    assert get_thread_count({"thread_count": 99}) == "32"
    assert get_thread_count({"thread_count": 0}) == "1"
    assert get_thread_count({"thread_count": 8}) == "8"
    assert get_thread_count({"thread_count": "bad"}) == "16"
    assert get_thread_count({}) == "16"

def test_construire_commande_base_structure():
    cmd = _cmd()
    assert cmd[0] == "EXE" and cmd[1] == "http://h/x.m3u8"
    assert cmd[cmd.index("--save-dir") + 1] == "/dossier"
    assert cmd[cmd.index("--save-name") + 1] == "nom"
    assert cmd[cmd.index("--tmp-dir") + 1] == "/tmp"

def test_construire_commande_auto_select_when_quality_auto():
    cmd = _cmd(settings={"qualite": "auto"})
    assert "--auto-select" in cmd
    assert "--video-filter" not in cmd

def test_construire_commande_quality_filter():
    for q in ("1080", "720", "480"):
        cmd = _cmd(settings={"qualite": q})
        assert "-sv" in cmd
        assert f"res=x{q}:for=best" in cmd
        assert "-sa" in cmd and "best" in cmd
        assert "--video-filter" not in cmd
        assert "--auto-select" not in cmd

def test_construire_commande_headers_optional():
    cmd = _cmd()
    assert not any(h.startswith("Referer:") for h in cmd)
    assert not any(h.startswith("Cookie:") for h in cmd)
    cmd2 = _cmd(headers={"referer": "http://r", "cookie": "c=1"})
    assert any(h == "Referer: http://r" for h in cmd2)
    assert any(h == "Cookie: c=1" for h in cmd2)

def test_construire_commande_origin_fallback_for_referer():
    cmd = _cmd(headers={"origin": "http://o"})
    assert any(h == "Referer: http://o" for h in cmd)

def test_construire_commande_sanitizes_crlf_in_headers():
    cmd = _cmd(headers={"user-agent": "UA\r\ninjected"})
    ua_idx = [i for i, x in enumerate(cmd) if x.startswith("User-Agent:")]
    assert ua_idx and "\r" not in cmd[ua_idx[0]] and "\n" not in cmd[ua_idx[0]]

def test_interpreter_ligne_segments():
    st = {"phase": "init", "total_segs": 0}
    interpreter_ligne("Total 250 Segments found", st, None)
    assert st["total_segs"] == 250
    assert st["phase"] == "downloading"

def test_interpreter_ligne_phases():
    calls = []
    cb = lambda p, l: calls.append(p)
    st = {"phase": "downloading", "total_segs": 10}
    interpreter_ligne("Binary merging parts", st, cb)
    assert st["phase"] == "merging" and 96.0 in calls
    interpreter_ligne("Cleaning up", st, cb)
    assert 98.0 in calls
    interpreter_ligne("Done", st, cb)
    assert st["phase"] == "done" and 100.0 in calls
