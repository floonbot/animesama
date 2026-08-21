from datetime import UTC, datetime

import engine.download.methods._ytdlp_updater as up


def test_gere_ce_binaire():
    assert up._gere_ce_binaire("C:\\AnimeSama\\_internal\\bin\\yt-dlp.exe")
    assert up._gere_ce_binaire("/proj/bin/yt-dlp.exe")
    assert not up._gere_ce_binaire("/proj/tools/yt-dlp")
    assert not up._gere_ce_binaire("")


def test_desactive_sous_pytest():
    assert up._desactive() is True


def test_desactive_quand_frozen(monkeypatch):
    import sys as _sys

    monkeypatch.delitem(_sys.modules, "pytest", raising=False)
    monkeypatch.delenv("ANIMESAMA_NO_YTDLP_UPDATE", raising=False)

    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    assert up._desactive() is True

    monkeypatch.delattr(_sys, "frozen", raising=False)
    assert up._desactive() is False


def test_frozen_bloque_le_telechargement(monkeypatch):
    import sys as _sys

    import engine.download.methods.ytdlp_engine as yt

    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(yt, "_get_ytdlp_path", lambda: "/x/bin/yt-dlp.exe")
    monkeypatch.setattr(up, "_version_date", lambda exe: datetime(2020, 1, 1, tzinfo=UTC))
    appels = []
    monkeypatch.setattr(up, "_telecharger_latest", lambda dest: appels.append(dest) or True)

    up.verifier_et_mettre_a_jour()

    assert appels == []


def test_age_jours():
    vieux = datetime(2020, 1, 1, tzinfo=UTC)
    assert up._age_jours(vieux) > 1000


def test_update_telecharge_si_perime(monkeypatch):
    import engine.download.methods.ytdlp_engine as yt
    monkeypatch.setattr(up, "_desactive", lambda: False)
    monkeypatch.setattr(yt, "_get_ytdlp_path", lambda: "/x/bin/yt-dlp.exe")
    monkeypatch.setattr(up, "_version_date", lambda exe: datetime(2020, 1, 1, tzinfo=UTC))
    appels = []
    monkeypatch.setattr(up, "_telecharger_latest", lambda dest: appels.append(dest) or True)
    up.verifier_et_mettre_a_jour()
    assert appels == ["/x/bin/yt-dlp.exe"]


def test_update_saute_si_recent(monkeypatch):
    import engine.download.methods.ytdlp_engine as yt
    monkeypatch.setattr(up, "_desactive", lambda: False)
    monkeypatch.setattr(yt, "_get_ytdlp_path", lambda: "/x/bin/yt-dlp.exe")
    monkeypatch.setattr(up, "_version_date", lambda exe: datetime.now(UTC))
    appels = []
    monkeypatch.setattr(up, "_telecharger_latest", lambda dest: appels.append(dest) or True)
    up.verifier_et_mettre_a_jour()
    assert appels == []


def test_update_saute_si_binaire_non_gere(monkeypatch):
    import engine.download.methods.ytdlp_engine as yt
    monkeypatch.setattr(up, "_desactive", lambda: False)
    monkeypatch.setattr(yt, "_get_ytdlp_path", lambda: "/usr/local/scripts/yt-dlp")
    appels = []
    monkeypatch.setattr(up, "_telecharger_latest", lambda dest: appels.append(dest) or True)
    up.verifier_et_mettre_a_jour()
    assert appels == []
