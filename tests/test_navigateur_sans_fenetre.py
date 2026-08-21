"""Le sniff tourne sans fenetre, et sait degrader si le canal manque.

L'interception essaie jusqu'a quatre lecteurs en parallele : en mode visible,
quatre fenetres Chromium s'ouvraient pendant un telechargement. La mesure du
11 aout 2026 (17 lecteurs, trois configurations) donne le meme taux de capture
dans les trois cas — le mode visible ne rapportait rien.
"""

import asyncio

import pytest

import engine.download.interceptor as itc
from engine.config import settings


class _FauxChromium:
    def __init__(self, echoue_avec_canal: bool = False) -> None:
        self.appels: list[dict] = []
        self._echoue_avec_canal = echoue_avec_canal

    async def launch(self, **kw):
        self.appels.append(kw)
        if self._echoue_avec_canal and kw.get("channel"):
            raise RuntimeError("chromium distribution is not installed")
        return f"browser({kw.get('channel') or 'shell'})"


class _FauxPW:
    def __init__(self, chromium) -> None:
        self.chromium = chromium


def test_le_defaut_est_sans_fenetre_sur_le_binaire_complet():
    assert settings.BROWSER_HEADLESS is True
    assert settings.BROWSER_CHANNEL == "chromium"


def test_le_lancement_demande_le_canal_chromium(monkeypatch):
    monkeypatch.setattr(itc, "BROWSER_HEADLESS", True)
    monkeypatch.setattr(itc, "BROWSER_CHANNEL", "chromium")
    chromium = _FauxChromium()

    resultat = asyncio.run(itc._lancer_chromium(_FauxPW(chromium)))

    assert resultat == "browser(chromium)"
    assert chromium.appels[0]["headless"] is True
    assert chromium.appels[0]["channel"] == "chromium"


def test_un_canal_absent_retombe_sur_le_shell(monkeypatch, caplog):
    monkeypatch.setattr(itc, "BROWSER_HEADLESS", True)
    monkeypatch.setattr(itc, "BROWSER_CHANNEL", "chromium")
    chromium = _FauxChromium(echoue_avec_canal=True)

    with caplog.at_level("WARNING"):
        resultat = asyncio.run(itc._lancer_chromium(_FauxPW(chromium)))

    assert resultat == "browser(shell)"
    assert len(chromium.appels) == 2
    assert chromium.appels[1].get("channel") is None
    assert chromium.appels[1]["headless"] is True
    assert any("repli sur chrome-headless-shell" in r.message for r in caplog.records)


def test_sans_canal_configure_l_echec_remonte(monkeypatch):
    monkeypatch.setattr(itc, "BROWSER_CHANNEL", "")
    monkeypatch.setattr(itc, "BROWSER_HEADLESS", True)

    class _Casse:
        async def launch(self, **kw):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(itc._lancer_chromium(_FauxPW(_Casse())))


def test_l_annulation_n_est_pas_convertie_en_repli(monkeypatch):
    monkeypatch.setattr(itc, "BROWSER_CHANNEL", "chromium")

    class _Annule:
        appels = 0

        async def launch(self, **kw):
            type(self).appels += 1
            raise asyncio.CancelledError

    faux = _Annule()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(itc._lancer_chromium(_FauxPW(faux)))
    assert _Annule.appels == 1


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [("0", False), ("false", False), ("FALSE", False), ("no", False), ("off", False),
     ("1", True), ("true", True), ("yes", True), (" true ", True)],
)
def test_env_bool_ne_prend_plus_zero_pour_un_oui(monkeypatch, brut, attendu):
    # L'ancien « getenv(...).lower() != "false" » rendait True pour « 0 ».
    monkeypatch.setenv("SONDE_BOOL", brut)
    assert settings._env_bool("SONDE_BOOL", not attendu) is attendu


def test_env_bool_rend_le_defaut_si_absent(monkeypatch):
    monkeypatch.delenv("SONDE_BOOL", raising=False)
    assert settings._env_bool("SONDE_BOOL", True) is True
    assert settings._env_bool("SONDE_BOOL", False) is False


@pytest.mark.parametrize("vide", ["", "   ", "\t"])
def test_une_valeur_vide_vaut_le_defaut_pas_un_non(monkeypatch, vide):
    # « DL_ABANDON_LENT= » dans un .env veut dire « je n'ai rien choisi ».
    # Le lire comme un « non » coupait l'abandon sur debit lent en silence.
    monkeypatch.setenv("SONDE_BOOL", vide)
    assert settings._env_bool("SONDE_BOOL", True) is True
    assert settings._env_bool("SONDE_BOOL", False) is False
