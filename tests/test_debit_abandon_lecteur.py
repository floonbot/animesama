import asyncio

import pytest

from engine.domain.exceptions import DownloadCancelled
from engine.download import _debit as debit
from engine.download import _domain_strategy as strategy
from engine.download import pipeline
from engine.download.methods._ytdlp_parsing import parser_debit
from engine.download.queue import CancelToken

MO = 1024.0 * 1024.0


class FakeQueue:
    def __init__(self):
        self._cancelled = CancelToken()
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


class _Horloge:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def avancer(self, s):
        self.t += s


@pytest.fixture(autouse=True)
def _etat_propre():
    debit.reinitialiser()
    yield
    debit.reinitialiser()


@pytest.fixture
def horloge(monkeypatch):
    h = _Horloge()
    monkeypatch.setattr(debit, "time", h)
    return h


def _telecharger(surveillant, horloge, *, debit_bps, taille_mo, duree_s, pct_depart=0.0,
                 pas_s=5.0):
    """Simule un telechargement lineaire et rend le pourcentage atteint."""
    pct = pct_depart
    ecoule = 0.0
    surveillant.signaler_debit(pct, debit_bps)
    while ecoule < duree_s:
        horloge.avancer(pas_s)
        ecoule += pas_s
        pct = min(100.0, pct + 100.0 * (debit_bps * pas_s) / (taille_mo * MO))
        surveillant.signaler_debit(pct, debit_bps)
    return pct


def test_parser_debit_lit_les_unites():
    assert parser_debit("[download]  42.5% of ~100.00MiB at 5.00MiB/s ETA 00:30") == (
        42.5, 5.0 * MO
    )
    pct, bps = parser_debit("[download]  12.0% of ~197.00MiB at 192.00KiB/s ETA 17:00")
    assert pct == 12.0
    assert bps == pytest.approx(192.0 * 1024.0)


def test_parser_debit_sur_une_sortie_reelle_de_yt_dlp():
    # Relevee sur bin/yt-dlp.exe 2026.07.04, telechargement direct sans aria2c.
    pct, bps = parser_debit("[download]   0.0% of    5.26MiB at  666.40KiB/s ETA 00:08")
    assert pct == 0.0
    assert bps == pytest.approx(666.40 * 1024.0)


def test_parser_debit_ignore_les_lignes_sans_mesure():
    assert parser_debit("[download]   7.0%") is None
    assert parser_debit("[download]  3.0% of ~10.00MiB at Unknown B/s ETA Unknown") is None
    assert parser_debit("autre chose") is None
    # Seule ligne emise quand aria2c telecharge : recapitulatif, pas progression.
    assert parser_debit("[download] 100% of    5.26MiB in 00:00:00 at 10.77MiB/s") is None


def test_surveillant_abandonne_un_hote_qui_bride(horloge):
    base = CancelToken()
    s = debit.SurveillantDebit(base, hote="video.sibnet.ru", alternatives=2)

    _telecharger(s, horloge, debit_bps=0.19 * MO, taille_mo=197.0, duree_s=120.0)

    assert s.abandon_lenteur is True
    assert s[0] is True
    assert bool(s) is True
    assert "video.sibnet.ru" in s.motif


def test_surveillant_ne_coupe_pas_sans_lecteur_de_rechange(horloge):
    s = debit.SurveillantDebit(CancelToken(), hote="video.sibnet.ru", alternatives=0)

    _telecharger(s, horloge, debit_bps=0.19 * MO, taille_mo=197.0, duree_s=300.0)

    assert s.abandon_lenteur is False
    assert s[0] is False


def test_surveillant_ne_coupe_pas_un_debit_correct(horloge):
    s = debit.SurveillantDebit(CancelToken(), hote="video.sibnet.ru", alternatives=2)

    _telecharger(s, horloge, debit_bps=5.0 * MO, taille_mo=4000.0, duree_s=300.0)

    assert s.abandon_lenteur is False


def test_surveillant_ne_jette_pas_un_telechargement_presque_fini(horloge):
    s = debit.SurveillantDebit(CancelToken(), hote="video.sibnet.ru", alternatives=2)

    _telecharger(
        s, horloge, debit_bps=0.19 * MO, taille_mo=197.0, duree_s=300.0, pct_depart=90.0
    )

    assert s.abandon_lenteur is False


def test_surveillant_ne_coupe_pas_si_le_reste_est_court(horloge):
    s = debit.SurveillantDebit(CancelToken(), hote="video.sibnet.ru", alternatives=2)

    _telecharger(s, horloge, debit_bps=0.19 * MO, taille_mo=20.0, duree_s=90.0)

    assert s.abandon_lenteur is False


def test_le_seuil_monte_avec_le_meilleur_debit_connu_de_l_hote(horloge):
    lent = debit.SurveillantDebit(CancelToken(), hote="rapide.example", alternatives=2)
    _telecharger(lent, horloge, debit_bps=1.5 * MO, taille_mo=4000.0, duree_s=300.0)
    assert lent.abandon_lenteur is False

    debit.noter_debit_hote("rapide.example", 9.0 * MO)
    apres = debit.SurveillantDebit(CancelToken(), hote="rapide.example", alternatives=2)
    _telecharger(apres, horloge, debit_bps=1.5 * MO, taille_mo=4000.0, duree_s=300.0)

    assert apres.abandon_lenteur is True


def test_le_seuil_adaptatif_est_plafonne(horloge):
    debit.noter_debit_hote("tres-rapide.example", 200.0 * MO)
    s = debit.SurveillantDebit(CancelToken(), hote="tres-rapide.example", alternatives=2)

    _telecharger(s, horloge, debit_bps=4.0 * MO, taille_mo=8000.0, duree_s=300.0)

    assert s.abandon_lenteur is False


def test_le_token_relaie_l_annulation_utilisateur(horloge):
    base = CancelToken()
    s = debit.SurveillantDebit(base, hote="h", alternatives=2)
    assert s[0] is False
    base.set()
    assert s[0] is True
    assert s.is_cancelled() is True
    assert s.abandon_lenteur is False


def test_la_politique_borne_le_nombre_d_abandons():
    politique = debit.PolitiqueDebit(alternatives=3, max_abandons=1)
    premier = politique.surveillant(CancelToken(), "a.example", 2)
    assert premier._actif is True
    politique.enregistrer_abandon("a.example")
    second = politique.surveillant(CancelToken(), "b.example", 2)
    assert second._actif is False


def test_un_hote_lent_est_declasse_pas_exclu():
    lecteurs = [
        {"src": "https://video.sibnet.ru/v", "host": "video.sibnet.ru"},
        {"src": "https://sendvid.com/v", "host": "sendvid.com"},
    ]
    debit.marquer_hote_lent("video.sibnet.ru")

    ytdlp, _autres = strategy.partition_lecteurs(lecteurs)

    assert [l["host"] for l in ytdlp] == ["sendvid.com", "video.sibnet.ru"]


def _patch_pipeline(monkeypatch):
    monkeypatch.setattr("engine.utils.security.is_safe_url", lambda u: True)
    monkeypatch.setattr(pipeline, "domain_mark_used", lambda d: None)

    async def no_wait(domain):
        return None

    monkeypatch.setattr(pipeline, "domain_wait", no_wait)


LENT = {"src": "https://video.sibnet.ru/v", "host": "video.sibnet.ru"}
RAPIDE = {"src": "https://sendvid.com/v", "host": "sendvid.com"}


def test_cascade_passe_au_lecteur_suivant_quand_le_premier_bride(monkeypatch):
    _patch_pipeline(monkeypatch)
    vus = []

    async def pool(fn, src, dossier, nom_ep, headers, jeton, on_progress):
        vus.append(src)
        if "sibnet" in src:
            jeton._abandon = True
            jeton._motif = "video.sibnet.ru ne délivre que 0.2 MB/s"
            raise DownloadCancelled()
        return "out.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)
    q = FakeQueue()
    out = asyncio.run(
        pipeline._ytdlp_sur_lecteurs(
            [LENT, RAPIDE], "/tmp", "ep", "[x]", q,
            politique=debit.PolitiqueDebit(alternatives=0),
        )
    )

    assert out == "out.mp4"
    assert vus == [LENT["src"], RAPIDE["src"]]
    assert q._cancelled.is_cancelled() is False
    lignes = [d["line"] for ev, d in q.events if ev == "episode_progress"]
    assert any("trop lent" in ligne for ligne in lignes)
    assert debit.hote_lent("video.sibnet.ru") is True


def test_le_lecteur_lent_est_repris_si_aucun_autre_n_aboutit(monkeypatch):
    _patch_pipeline(monkeypatch)
    essais = []

    async def pool(fn, src, dossier, nom_ep, headers, jeton, on_progress):
        essais.append(src)
        if "sendvid" in src:
            return None
        if getattr(jeton, "abandon_lenteur", None) is not None:
            jeton._abandon = True
            jeton._motif = "lent"
            raise DownloadCancelled()
        return "lent_mais_complet.mp4"

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)
    q = FakeQueue()
    out = asyncio.run(
        pipeline._ytdlp_sur_lecteurs(
            [LENT, RAPIDE], "/tmp", "ep", "[x]", q,
            politique=debit.PolitiqueDebit(alternatives=0),
        )
    )

    assert out == "lent_mais_complet.mp4"
    assert essais == [LENT["src"], RAPIDE["src"], LENT["src"]]


def test_l_annulation_utilisateur_reste_prioritaire_sur_l_abandon(monkeypatch):
    _patch_pipeline(monkeypatch)
    q = FakeQueue()

    async def pool(fn, src, dossier, nom_ep, headers, jeton, on_progress):
        jeton._abandon = True
        q._cancelled.set()
        raise DownloadCancelled()

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    with pytest.raises(DownloadCancelled):
        asyncio.run(
            pipeline._ytdlp_sur_lecteurs(
                [LENT, RAPIDE], "/tmp", "ep", "[x]", q,
                politique=debit.PolitiqueDebit(alternatives=0),
            )
        )


class _FakeProc:
    def __init__(self, lignes, returncode=0):
        self.stdout = iter(lignes)
        self.returncode = returncode
        self.pid = 4321

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None

    def terminate(self):
        return None


def _patch_ytdlp_engine(monkeypatch, lignes):
    import threading

    import engine.config.user_settings as user_settings
    from engine.download.methods import ytdlp_engine

    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "_nettoyer_fragments", lambda d, n: 0)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n, avant=None: None)
    monkeypatch.setattr(
        ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event()
    )
    monkeypatch.setattr(ytdlp_engine, "_terminate_tree", lambda p: None)
    monkeypatch.setattr(ytdlp_engine, "finaliser_process", lambda *a, **k: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    monkeypatch.setattr(
        ytdlp_engine.subprocess, "Popen", lambda cmd, *a, **k: _FakeProc(lignes)
    )
    return ytdlp_engine


def test_ytdlp_signale_le_debit_au_token(tmp_path, monkeypatch):
    ytdlp_engine = _patch_ytdlp_engine(monkeypatch, [
        "[download]  12.0% of ~197.00MiB at 192.00KiB/s ETA 17:00\n",
        "[download]  13.0% of ~197.00MiB at Unknown B/s ETA Unknown\n",
        "[download]  14.0% of ~197.00MiB at 1.00MiB/s ETA 03:00\n",
    ])

    recu = []

    class _Sonde:
        def __bool__(self):
            return False

        def __getitem__(self, _i):
            return False

        def signaler_debit(self, pct, bps):
            recu.append((pct, bps))

    ytdlp_engine.ytdlp_download("http://h/v", str(tmp_path), "ep", cancelled=_Sonde())

    assert recu == [(12.0, 192.0 * 1024.0), (14.0, 1.0 * MO)]


def test_ytdlp_sort_en_annulation_quand_le_surveillant_coupe(tmp_path, monkeypatch):
    ytdlp_engine = _patch_ytdlp_engine(monkeypatch, [
        "[download]  12.0% of ~197.00MiB at 192.00KiB/s ETA 17:00\n",
        "[download]  13.0% of ~197.00MiB at 192.00KiB/s ETA 17:00\n",
    ])

    class _Coupe:
        def __init__(self):
            self.coupe = False

        def __bool__(self):
            return True

        def __getitem__(self, _i):
            return self.coupe

        def signaler_debit(self, pct, bps):
            self.coupe = True

    with pytest.raises(DownloadCancelled):
        ytdlp_engine.ytdlp_download("http://h/v", str(tmp_path), "ep", cancelled=_Coupe())


def test_sans_politique_l_annulation_remonte_telle_quelle(monkeypatch):
    _patch_pipeline(monkeypatch)

    async def pool(*a, **k):
        raise DownloadCancelled()

    monkeypatch.setattr(pipeline, "_run_in_pool", pool)

    with pytest.raises(DownloadCancelled):
        asyncio.run(pipeline._ytdlp_sur_lecteurs([LENT], "/tmp", "ep", "[x]", FakeQueue()))
