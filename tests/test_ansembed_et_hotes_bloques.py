"""Lecteur ansembed et hebergeurs qui refusent la connexion (releves du 08/11/2026).

- ansembed.net, lecteur propre au site, servait 345 liens sur 60 oeuvres sans
  module : il passait par le navigateur alors que yt-dlp le lit tel quel ;
- video.sibnet.ru repond « 403 Request forbidden by administrative rules » a
  l'adresse de l'utilisateur : chaque episode attendait ~70 s une penalite
  pour reprendre le meme 403, et chaque 403 comptait comme un ban.
"""

import asyncio

import pytest

from engine.download import _hotes_bloques as hb
from engine.download import pipeline
from engine.download._domain_strategy import partition_lecteurs, strategie_lecteur
from engine.download.extractor.registry import get_extractor
from tests.test_pipeline_orchestration import FakeQueue

SIBNET = {"src": "https://video.sibnet.ru/shell.php?videoid=6095661", "host": "video.sibnet.ru"}
ANSEMBED = {"src": "https://ansembed.net/embed-ejx5fe0j9fyk.html", "host": "ansembed.net"}


@pytest.fixture(autouse=True)
def _etat_propre(monkeypatch):
    from engine.download import _host_breakers

    monkeypatch.setattr(hb, "_bloques", {})
    monkeypatch.setattr(_host_breakers, "_breakers", {})


def test_ansembed_passe_par_yt_dlp_avant_les_mp4_progressifs():
    ext = get_extractor(ANSEMBED["src"])
    assert (ext.name, ext.prefer_ytdlp, ext.referer) == ("ansembed", True, "https://ansembed.net/")
    assert strategie_lecteur(ANSEMBED) == "ytdlp_first"
    ytdlp, autres = partition_lecteurs([SIBNET, ANSEMBED])
    assert [l["host"] for l in ytdlp] == ["ansembed.net", "video.sibnet.ru"]
    assert autres == []


class _Rep:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


@pytest.mark.parametrize("rep,attendu", [
    (_Rep(403, "<h1>403 Forbidden</h1>\nRequest forbidden by administrative rules.\n"), True),
    (_Rep(403, "<h1>403 Forbidden</h1> rate limited"), False),  # limite de debit : comme avant
    (_Rep(200, "Request forbidden by administrative rules"), False),
])
def test_sonde_ne_reconnait_que_le_refus_de_l_adresse(monkeypatch, rep, attendu):
    monkeypatch.setattr("requests.get", lambda *a, **k: rep)
    assert hb.sonder_blocage(SIBNET["src"]) is attendu


def test_sonde_injoignable_ne_bloque_rien(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise requests.ConnectionError("hors ligne")

    monkeypatch.setattr("requests.get", _boom)
    assert hb.sonder_blocage(SIBNET["src"]) is False


def test_blocage_expire(monkeypatch):
    hb.marquer_bloque("www.video.sibnet.ru")
    assert hb.hote_bloque("video.sibnet.ru") and hb.hotes_bloques() == ["video.sibnet.ru"]
    hb._bloques["video.sibnet.ru"] = 0.0  # echeance depassee
    assert not hb.hote_bloque("video.sibnet.ru")


def _cascade(monkeypatch, sonde: bool):
    from engine.download.methods import ytdlp_engine

    monkeypatch.setattr(pipeline, "_motif_url_refusee", lambda url: None)

    async def _sans_attente(d):
        return None

    monkeypatch.setattr(pipeline, "domain_wait", _sans_attente)
    penalites: list[str] = []
    monkeypatch.setattr(pipeline, "domain_apply_penalty", penalites.append)
    monkeypatch.setattr(pipeline, "sonder_blocage", lambda url, *a: sonde)
    essais: list[str] = []

    async def pool(fn, src, *a):
        essais.append(src)
        if "sibnet" in src:
            raise ytdlp_engine.RateLimitError("video.sibnet.ru")
        return "D:/dl/ep.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)
    q = FakeQueue()
    with pipeline._collecte_causes() as causes:
        out = asyncio.run(pipeline._passe_ytdlp(
            [SIBNET, ANSEMBED], "D:/dl", "ep", "[x] E001", q, "", None, []))
    return out, penalites, essais, causes, q


def test_refus_de_l_adresse_ecarte_l_hote_sans_penalite(monkeypatch):
    out, penalites, essais, causes, q = _cascade(monkeypatch, sonde=True)

    assert out == "D:/dl/ep.mp4"
    assert penalites == []  # ni attente de 90 s, ni « ban » pour la pause globale
    assert hb.hote_bloque("video.sibnet.ru")
    assert "refuse cette connexion" in causes[-1]
    lignes = [d.get("line", "") for ev, d in q.events if ev == "episode_progress"]
    assert any("refuse cette connexion" in ligne for ligne in lignes)

    # Episode suivant : sibnet n'est meme plus propose.
    ytdlp, _ = partition_lecteurs([SIBNET, ANSEMBED])
    assert [l["host"] for l in ytdlp] == ["ansembed.net"]
    assert pipeline.sans_hotes_bloques([SIBNET, ANSEMBED]) == [ANSEMBED]


def test_un_403_ordinaire_garde_sa_penalite(monkeypatch):
    out, penalites, essais, causes, q = _cascade(monkeypatch, sonde=False)

    assert out == "D:/dl/ep.mp4"
    assert penalites == ["video.sibnet.ru"]
    assert not hb.hote_bloque("video.sibnet.ru")


def test_le_diagnostic_montre_les_hotes_qui_refusent():
    from web.api.routes.health import _health_breakers

    hb.marquer_bloque("video.sibnet.ru")
    assert _health_breakers()["bloques"] == ["video.sibnet.ru"]
