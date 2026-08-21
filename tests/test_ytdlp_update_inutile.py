"""Observé en lançant l'app : « yt-dlp date de 32 jours — mise a jour... » suivi de
« yt-dlp mis a jour (2026-07-04) » à *chaque* démarrage, alors que 2026.07.04 est
déjà la dernière version publiée.

La sonde ne regardait que l'âge de la version locale : dès qu'upstream ne publie
rien pendant 14 jours, l'app retéléchargeait ~30 Mo et réécrivait bin/yt-dlp.exe
à chaque lancement. On compare maintenant au tag distant avant de télécharger.
"""

import sys
from datetime import UTC, datetime

import engine.download.methods._ytdlp_updater as up
import engine.download.methods.ytdlp_engine as yt


def _actif(monkeypatch):
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    monkeypatch.delenv("ANIMESAMA_NO_YTDLP_UPDATE", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)


def _binaire_ancien(monkeypatch, date=(2026, 7, 4)):
    monkeypatch.setattr(yt, "_get_ytdlp_path", lambda: "/proj/bin/yt-dlp.exe")
    monkeypatch.setattr(up, "_version_date", lambda exe: datetime(*date, tzinfo=UTC))
    monkeypatch.setattr(up, "_age_jours", lambda released: 32.0)


def test_pas_de_telechargement_si_le_tag_distant_est_identique(monkeypatch):
    _actif(monkeypatch)
    _binaire_ancien(monkeypatch)
    monkeypatch.setattr(up, "_tag_distant", lambda: "2026.07.04")
    appels: list = []
    monkeypatch.setattr(up, "_telecharger_latest", lambda dest: appels.append(dest) or True)

    up.verifier_et_mettre_a_jour()

    assert appels == []


def test_telechargement_si_le_tag_distant_est_plus_recent(monkeypatch):
    _actif(monkeypatch)
    _binaire_ancien(monkeypatch)
    monkeypatch.setattr(up, "_tag_distant", lambda: "2026.08.01")
    appels: list = []
    monkeypatch.setattr(up, "_telecharger_latest", lambda dest: appels.append(dest) or True)

    up.verifier_et_mettre_a_jour()

    assert appels == ["/proj/bin/yt-dlp.exe"]


def test_tag_distant_illisible_conserve_l_ancien_comportement(monkeypatch):
    _actif(monkeypatch)
    _binaire_ancien(monkeypatch)
    monkeypatch.setattr(up, "_tag_distant", lambda: None)
    appels: list = []
    monkeypatch.setattr(up, "_telecharger_latest", lambda dest: appels.append(dest) or True)

    up.verifier_et_mettre_a_jour()

    assert appels == ["/proj/bin/yt-dlp.exe"]


def test_tag_distant_parse_la_redirection(monkeypatch):
    class _R:
        headers = {"Location": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.07.04"}

    monkeypatch.setattr("requests.head", lambda *a, **k: _R())
    assert up._tag_distant() == "2026.07.04"


def test_tag_distant_rejette_une_cible_inattendue(monkeypatch):
    class _R:
        headers = {"Location": "https://github.com/yt-dlp/yt-dlp/releases"}

    monkeypatch.setattr("requests.head", lambda *a, **k: _R())
    assert up._tag_distant() is None


def test_tag_distant_hors_ligne_renvoie_none(monkeypatch):
    def _boum(*a, **k):
        raise OSError("pas de réseau")

    monkeypatch.setattr("requests.head", _boum)
    assert up._tag_distant() is None
