import engine.download.methods.ytdlp_engine as ytdlp_engine


def test_nettoyer_fragments_spares_prefix_sibling_episode(tmp_path):
    nom = "Show - S01E01 VOSTFR"

    final = tmp_path / (nom + ".mp4")
    final.write_bytes(b"video")
    own_frag = tmp_path / (nom + ".mp4-Frag0")
    own_frag.write_bytes(b"junk")

    sibling_frag = tmp_path / ("Show - S01E010 VOSTFR.mp4-Frag0")
    sibling_frag.write_bytes(b"sibling-in-progress")
    sibling_part = tmp_path / ("Show - S01E010 VOSTFR.part")
    sibling_part.write_bytes(b"sibling-part")

    n = ytdlp_engine._nettoyer_fragments(str(tmp_path), nom)

    assert n == 1
    assert final.exists()
    assert not own_frag.exists()
    assert sibling_frag.exists()
    assert sibling_part.exists()


def test_nettoyer_fragments_still_removes_own_temps(tmp_path):
    nom = "Alpha - S01E01 VOSTFR"
    final = tmp_path / (nom + ".mp4")
    final.write_bytes(b"video")
    for suffix in (".mp4-Frag0", ".f137.mp4-Frag0", ".part", ".ytdl", ".mp4.part-Frag2"):
        (tmp_path / (nom + suffix)).write_bytes(b"junk")

    n = ytdlp_engine._nettoyer_fragments(str(tmp_path), nom)

    assert n == 5
    assert final.exists()
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [nom + ".mp4"]
