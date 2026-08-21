"""Cadence d'emission de la progression yt-dlp.

nm3u8dl emet une fois par seconde, ffmpeg toutes les 0,5 s ; yt-dlp emettait
sur *chaque* ligne de stdout, soit un evenement SSE serialise et diffuse a
tous les clients plusieurs fois par seconde. Trois moteurs, trois cadences.
"""

import pytest


@pytest.fixture
def horloge(monkeypatch):
    from engine.download.methods import ytdlp_engine

    faux = {"t": 1000.0}
    monkeypatch.setattr(ytdlp_engine.time, "monotonic", lambda: faux["t"])
    return faux


def _ligne(pct: float) -> str:
    return f"[download]  {pct:.1f}% of 100.00MiB at 5.00MiB/s ETA 00:20"


def test_progression_throttlee(horloge):
    from engine.download.methods import ytdlp_engine

    recu = []
    etat = ytdlp_engine._nouvel_etat_progression()
    for i in range(40):
        horloge["t"] += 0.05
        ytdlp_engine._dispatch_ligne_ytdlp(
            _ligne(i), "host.tld", lambda p, t: recu.append((p, t)), etat
        )
    assert len(recu) <= 6, f"{recu and len(recu)} emissions pour 2 s de progression"
    assert recu, "aucune progression emise"


def test_premiere_ligne_emise_immediatement(horloge):
    from engine.download.methods import ytdlp_engine

    recu = []
    etat = ytdlp_engine._nouvel_etat_progression()
    ytdlp_engine._dispatch_ligne_ytdlp(_ligne(1), "h", lambda p, t: recu.append(p), etat)
    assert recu == [1.0]


def test_fin_de_telechargement_toujours_emise(horloge):
    from engine.download.methods import ytdlp_engine

    recu = []
    etat = ytdlp_engine._nouvel_etat_progression()
    ytdlp_engine._dispatch_ligne_ytdlp(_ligne(1), "h", lambda p, t: recu.append(p), etat)
    horloge["t"] += 0.01
    ytdlp_engine._dispatch_ligne_ytdlp(_ligne(100), "h", lambda p, t: recu.append(p), etat)
    assert 100.0 in recu, "le 100 % est avale par le throttle, la barre reste bloquee"


def test_messages_non_progression_jamais_throttles(horloge):
    from engine.download.methods import ytdlp_engine

    recu = []
    etat = ytdlp_engine._nouvel_etat_progression()
    cb = lambda p, t: recu.append(t)  # noqa: E731
    ytdlp_engine._dispatch_ligne_ytdlp(_ligne(1), "h", cb, etat)
    horloge["t"] += 0.01
    ytdlp_engine._dispatch_ligne_ytdlp("[Merger] Merging formats", "h", cb, etat)
    horloge["t"] += 0.01
    ytdlp_engine._dispatch_ligne_ytdlp("[aria2c] go", "h", cb, etat)
    assert any("Assemblage" in t for t in recu)
    assert any("accéléré" in t for t in recu)


def test_403_toujours_signale(horloge):
    from engine.download.methods import ytdlp_engine

    recu = []
    etat = ytdlp_engine._nouvel_etat_progression()
    cb = lambda p, t: recu.append(t)  # noqa: E731
    ytdlp_engine._dispatch_ligne_ytdlp(_ligne(1), "h", cb, etat)
    horloge["t"] += 0.01
    got = ytdlp_engine._dispatch_ligne_ytdlp("HTTP Error 403: Forbidden", "h", cb, etat)
    assert got is True
    assert any("occupé" in t for t in recu)


def test_etat_absent_reste_supporte(horloge):
    from engine.download.methods import ytdlp_engine

    recu = []
    ytdlp_engine._dispatch_ligne_ytdlp(_ligne(5), "h", lambda p, t: recu.append(p), None)
    assert recu == [5.0]
