from engine.download.methods._ffmpeg_parsing import (
    ProgressState,
    construire_commande,
    construire_texte_progress,
    parse_progress_line,
)


def test_construire_commande_structure():
    c = construire_commande("ff", "http://h/x.m3u8", "/d/out.mp4", {})
    assert c[0] == "ff"
    assert c[-1] == "/d/out.mp4"
    assert c[c.index("-i") + 1] == "http://h/x.m3u8"
    assert "-c" in c and c[c.index("-c") + 1] == "copy"
    assert "-progress" in c and c[c.index("-progress") + 1] == "pipe:1"

def test_construire_commande_headers_optional():
    c = construire_commande("ff", "http://h", "/o.mp4", {})
    assert "-referer" not in c
    assert not any(x.startswith("Cookie:") for x in c)
    c2 = construire_commande("ff", "http://h", "/o.mp4", {"referer": "http://r", "cookie": "k=1"})
    assert "-referer" in c2 and "http://r" in c2
    assert any("Cookie: k=1" in x for x in c2)

def test_construire_commande_origin_fallback():
    c = construire_commande("ff", "http://h", "/o.mp4", {"origin": "http://o"})
    assert "http://o" in c

def test_parse_progress_line_fields():
    st = ProgressState()
    parse_progress_line("out_time=01:02:03", st)
    assert st.out_time_s == 3723.0
    parse_progress_line("total_size=2097152", st)
    assert st.total_size == 2097152
    parse_progress_line("speed= 2.5x", st)
    assert st.speed == 2.5
    parse_progress_line("bitrate= 800.0kbits/s", st)
    assert st.bitrate == 800.0
    assert st.done is False
    parse_progress_line("progress=end", st)
    assert st.done is True

def test_construire_texte_progress_percentage():
    st = ProgressState()
    parse_progress_line("out_time=00:01:30", st)
    parse_progress_line("total_size=1048576", st)
    pct, txt = construire_texte_progress(st, 180.0)
    assert abs(pct - 50.0) < 0.1
    assert "00:01:30" in txt

def test_construire_texte_progress_no_duration():
    st = ProgressState()
    parse_progress_line("out_time=00:00:10", st)
    pct, txt = construire_texte_progress(st, 0.0)
    assert pct == 0.0
    assert txt.startswith("⏱")
