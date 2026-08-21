import engine.download.methods.ytdlp_engine as ytdlp_engine
from engine.download.methods._ytdlp_parsing import construire_commande


def test_command_no_longer_keeps_fragments():
    cmd = construire_commande("yt", "http://h/v", "/d", "n", {}, "auto", aria2c="/bin/aria2c")
    assert "--keep-fragments" not in cmd


def test_nettoyer_fragments_removes_frags_and_temps_keeps_video(tmp_path):
    nom = "my ridiculous reincarnation - S01E001 VOSTFR"
    final = tmp_path / (nom + ".mp4")
    final.write_bytes(b"video")
    autre = tmp_path / "autre episode.mp4"
    autre.write_bytes(b"x")

    leftovers = [
        nom + ".mp4-Frag0",
        nom + ".mp4-Frag1",
        nom + ".f137.mp4-Frag0",
        nom + ".part",
        nom + ".ytdl",
        nom + ".mp4.part-Frag2",
    ]
    for f in leftovers:
        (tmp_path / f).write_bytes(b"junk")

    n = ytdlp_engine._nettoyer_fragments(str(tmp_path), nom)

    assert n == len(leftovers)
    assert final.exists()
    assert autre.exists()
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == sorted([nom + ".mp4", "autre episode.mp4"])


def test_nettoyer_fragments_missing_dir_is_safe(tmp_path):
    assert ytdlp_engine._nettoyer_fragments(str(tmp_path / "nope"), "x") == 0


def test_nettoyer_fragments_removes_unknown_cruft_keeps_video(tmp_path):
    nom = "Tomb Raider King - S01E001 VOSTFR"
    final = tmp_path / (nom + ".mp4")
    final.write_bytes(b"video")
    (tmp_path / (nom + ".unknown")).write_bytes(b"x")
    (tmp_path / (nom + ".unknown_video")).write_bytes(b"y")

    n = ytdlp_engine._nettoyer_fragments(str(tmp_path), nom)

    assert n == 2
    assert final.exists()
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [nom + ".mp4"]
