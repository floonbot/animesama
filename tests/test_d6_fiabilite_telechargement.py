"""D6 — quatre défauts de fiabilité mesurés au second cycle.

1. `_record_host(host, "attempt")` comptait deux fois un lecteur repris par la
   seconde passe (C14) : `taux_succes_pct` en devenait pessimiste, et c'est cette
   valeur qui pilote le seuil des « hôtes dégradés » du diagnostic.

2. Le garde-fou anti-corruption posé sur yt-dlp au C14 n'existait ni pour ffmpeg
   ni pour nm3u8dl. Mesuré : ffmpeg laisse en place toute sortie au-dessus de
   2 Mo quand il échoue, et `nm3u8dl._trouver_fichier_final` **adopte** n'importe
   quel fichier de plus de 10 Mo portant le bon nom — y compris celui qu'un autre
   moteur a laissé derrière lui.

3. `_causes_echec` ne remontait que la dernière cause. Sur un épisode dont les
   quatre lecteurs échouent pour quatre raisons différentes, l'utilisateur en
   lisait une seule.

4. yt-dlp qui rend « code retour 0 mais aucun fichier » ne comptait pas comme un
   échec pour le disjoncteur de l'hôte : `ytdlp_download` renvoie `None` sans
   lever, et la boucle de `_passe_ytdlp` retombait sur le lecteur suivant sans
   appeler `_on_failure`. Le disjoncteur restait donc fermé indéfiniment et
   l'hôte reprenait un tour de cascade à chaque épisode — le symptôme rapporté
   sur `uqload.is`, dont la mesure a par ailleurs montré qu'il est bien vivant
   (HTTP 200) et n'a donc rien à faire dans `HOSTS_MORTS`.
"""

import asyncio
import threading

import pytest

from engine.domain.exceptions import DownloadCancelled
from engine.download import pipeline as P
from engine.download.methods import ffmpeg_engine, nm3u8dl

# ---------------------------------------------------------------------------
# 1. Comptage des tentatives
# ---------------------------------------------------------------------------


def test_le_lecteur_repris_ne_compte_qu_une_tentative(monkeypatch):
    appels: list[tuple[str, str]] = []
    monkeypatch.setattr(P, "_record_host", lambda h, o: appels.append((h, o)))

    passes = {"n": 0}

    async def _fausse_passe(lecteurs, dossier, nom, label, queue, referer, politique, lents,
                            compter_tentative=True):
        passes["n"] += 1
        for lec in lecteurs:
            if compter_tentative:
                P._record_host(lec["host"], "attempt")
        if passes["n"] == 1:
            lents.append(lecteurs[0])
            return None
        P._record_host(lecteurs[0]["host"], "ok")
        return "/tmp/ok.mp4"

    monkeypatch.setattr(P, "_passe_ytdlp", _fausse_passe)
    lecteurs = [{"src": "https://h.example/a", "host": "sibnet"}]

    res = asyncio.run(P._ytdlp_sur_lecteurs(lecteurs, "d", "n", "ep", object()))

    assert res == "/tmp/ok.mp4"
    assert appels.count(("sibnet", "attempt")) == 1
    assert appels.count(("sibnet", "ok")) == 1


def test_la_signature_de_passe_ytdlp_porte_le_drapeau():
    """La seconde passe reprend le meme lecteur : il a deja ete compte."""
    import inspect

    params = inspect.signature(P._passe_ytdlp).parameters
    assert "compter_tentative" in params
    assert params["compter_tentative"].default is True


# ---------------------------------------------------------------------------
# 2a. ffmpeg — la sortie partielle
# ---------------------------------------------------------------------------


class _ProcFfmpeg:
    def __init__(self, sortie, octets_par_ligne, lignes, returncode=1):
        self.returncode = returncode
        self.pid = 999
        self._sortie = sortie
        self._octets = octets_par_ligne
        self._lignes = list(lignes)
        self.stdout = iter(())
        self.stderr = self

    def __iter__(self):
        for ligne in self._lignes:
            if self._octets:
                with open(self._sortie, "ab") as f:
                    f.write(b"A" * self._octets)
            yield ligne

    def close(self):
        return None

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        return None

    def terminate(self):
        return None


def _preparer_ffmpeg(monkeypatch, proc):
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_terminate_tree", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(ffmpeg_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a, **k: 0.0)


def test_ffmpeg_supprime_sa_sortie_partielle_sur_echec(tmp_path, monkeypatch):
    """3 Mo ecrits puis abandon : au-dessus du seuil de 2 Mo, le fichier restait."""
    sortie = tmp_path / "ep.mp4"
    proc = _ProcFfmpeg(str(sortie), 1_000_000, ["frame=1"] * 3, returncode=1)
    _preparer_ffmpeg(monkeypatch, proc)

    res = ffmpeg_engine.ffmpeg_download("http://h.example/v.m3u8", str(tmp_path), "ep", {}, [False])

    assert res is None
    assert not sortie.exists()


def test_ffmpeg_supprime_sa_sortie_partielle_sur_annulation(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"

    class _Jeton:
        def __init__(self):
            self.n = 0

        def __bool__(self):
            return True

        def __getitem__(self, _i):
            self.n += 1
            return self.n > 2

    proc = _ProcFfmpeg(str(sortie), 1_500_000, ["frame=1"] * 6, returncode=0)
    _preparer_ffmpeg(monkeypatch, proc)

    with pytest.raises(DownloadCancelled):
        ffmpeg_engine.ffmpeg_download(
            "http://h.example/v.m3u8", str(tmp_path), "ep", {}, _Jeton()
        )

    assert not sortie.exists()


def test_ffmpeg_ne_touche_pas_a_un_fichier_qu_il_n_a_pas_ecrit(tmp_path, monkeypatch):
    """Meme regle que yt-dlp : un fichier complet, inchange, survit a un echec."""
    sortie = tmp_path / "ep.mp4"
    sortie.write_bytes(b"A" * 30_000_000)
    proc = _ProcFfmpeg(str(sortie), 0, ["Error: nope"], returncode=1)
    _preparer_ffmpeg(monkeypatch, proc)

    res = ffmpeg_engine.ffmpeg_download("http://h.example/v.m3u8", str(tmp_path), "ep", {}, [False])

    assert res is None
    assert sortie.exists()
    assert sortie.stat().st_size == 30_000_000


def test_ffmpeg_garde_sa_sortie_valide(tmp_path, monkeypatch):
    sortie = tmp_path / "ep.mp4"
    proc = _ProcFfmpeg(str(sortie), 3_000_000, ["frame=1"] * 3, returncode=0)
    _preparer_ffmpeg(monkeypatch, proc)

    res = ffmpeg_engine.ffmpeg_download("http://h.example/v.m3u8", str(tmp_path), "ep", {}, [False])

    assert res == str(sortie)
    assert sortie.exists()


# ---------------------------------------------------------------------------
# 2b. nm3u8dl — l'adoption d'un reliquat
# ---------------------------------------------------------------------------


def test_nm3u8dl_n_adopte_pas_un_reliquat_qu_il_n_a_pas_ecrit(tmp_path):
    """Un partiel de 11 Mo laisse par ffmpeg passait pour un succes nm3u8dl,
    et `skip_existants` le tenait ensuite pour un episode deja telecharge."""
    reliquat = tmp_path / "ep.mp4"
    reliquat.write_bytes(b"A" * 11 * 1024 * 1024)
    avant = nm3u8dl._sorties_video(str(tmp_path), "ep")

    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep", avant) is None


def test_nm3u8dl_accepte_le_fichier_qu_il_vient_d_ecrire(tmp_path):
    avant = nm3u8dl._sorties_video(str(tmp_path), "ep")
    produit = tmp_path / "ep.mp4"
    produit.write_bytes(b"A" * 11 * 1024 * 1024)

    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep", avant) == str(produit)


def test_nm3u8dl_accepte_un_fichier_qui_a_grossi(tmp_path):
    """Le mux ecrase la sortie : meme nom, taille differente — c'est bien la sienne."""
    produit = tmp_path / "ep.mp4"
    produit.write_bytes(b"A" * 11 * 1024 * 1024)
    avant = nm3u8dl._sorties_video(str(tmp_path), "ep")
    produit.write_bytes(b"A" * 25 * 1024 * 1024)

    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep", avant) == str(produit)


def test_nm3u8dl_accepte_une_reecriture_de_taille_identique(tmp_path):
    """Piege introduit en corrigeant : re-telecharger la meme source redonne tres
    plausiblement la meme taille. S'en tenir a la taille rejetterait un succes."""
    import os

    produit = tmp_path / "ep.mp4"
    produit.write_bytes(b"A" * 11 * 1024 * 1024)
    avant = nm3u8dl._sorties_video(str(tmp_path), "ep")

    # Meme taille, ecriture plus recente — c'est bien le mux de cette execution.
    produit.write_bytes(b"B" * 11 * 1024 * 1024)
    st = produit.stat()
    os.utime(produit, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep", avant) == str(produit)


def test_nm3u8dl_sans_instantane_garde_l_ancien_comportement(tmp_path):
    """Appelee sans `avant`, la fonction reste celle d'origine (compat appelants)."""
    fichier = tmp_path / "ep.mp4"
    fichier.write_bytes(b"A" * 11 * 1024 * 1024)

    assert nm3u8dl._trouver_fichier_final(str(tmp_path), "ep") == str(fichier)


# ---------------------------------------------------------------------------
# 3. Toutes les causes d'échec, pas seulement la dernière
# ---------------------------------------------------------------------------


def test_resume_causes_rend_la_cause_unique_telle_quelle():
    assert P._resumer_causes(["disque plein"]) == "disque plein"


def test_resume_causes_rend_toutes_les_causes():
    causes = ["sibnet trop lent", "403 sur vidmoly", "URL non autorisée", "disque plein"]
    resume = P._resumer_causes(causes)
    for c in causes:
        assert c in resume


def test_resume_causes_dedoublonne():
    assert P._resumer_causes(["même cause", "même cause"]) == "même cause"


def test_resume_causes_borne_et_annonce_les_omises():
    causes = [f"cause numero {i} " + "x" * 90 for i in range(5)]
    resume = P._resumer_causes(causes, limite=200)
    assert len(resume) <= 200
    assert "autre" in resume


def test_cascade_remonte_toutes_les_causes(monkeypatch):
    """Le chemin reel : quatre lecteurs, quatre motifs, un seul message."""
    monkeypatch.setattr(P, "RETRIES_EFFECTIFS", 1)

    async def _rien(*a, **k):
        P._noter_cause("sibnet : trop lent")
        P._noter_cause("vidmoly : 403")
        P._noter_cause("disque plein")
        return None

    monkeypatch.setattr(P, "_ytdlp_sur_lecteurs", _rien)
    monkeypatch.setattr(P, "_extraire_et_telecharger", _rien)

    class _Q:
        _cancelled = None

    fichier, erreur = asyncio.run(
        P._cascade_download(
            [{"src": "https://a.example/x", "host": "sibnet"}], [], "d", "n", "ep", _Q()
        )
    )

    assert fichier is None
    assert "trop lent" in erreur
    assert "403" in erreur
    assert "disque plein" in erreur


# ---------------------------------------------------------------------------
# 4. « Processus OK mais fichier introuvable » compte comme un échec
# ---------------------------------------------------------------------------


@pytest.fixture
def _passe_ytdlp_sans_fichier(monkeypatch):
    """Arme `_passe_ytdlp` sur un lecteur dont yt-dlp ne rend jamais de fichier."""
    from engine.download import _host_breakers as HB

    with HB._breakers_lock:
        HB._breakers.clear()

    async def _rien(*a, **k):
        return None

    monkeypatch.setattr(P, "_run_in_pool", _rien)
    monkeypatch.setattr(P, "_motif_url_refusee", lambda _src: None)
    monkeypatch.setattr(P, "domain_wait", _rien)
    monkeypatch.setattr(P, "domain_mark_used", lambda _d: None)
    monkeypatch.setattr(P, "hote_throttle", lambda _d: False)

    class _Q:
        _cancelled = None

    def _tourner(n: int, host: str = "sibnet") -> None:
        for _ in range(n):
            res = asyncio.run(P._passe_ytdlp(
                [{"src": "https://video.example/lecteur", "host": host}],
                "d", "n", "ep", _Q(), "", None, [],
            ))
            assert res is None

    yield _tourner

    with HB._breakers_lock:
        HB._breakers.clear()


def test_ytdlp_sans_fichier_compte_un_echec_pour_le_disjoncteur(_passe_ytdlp_sans_fichier):
    """Le lecteur qui ne rend rien doit finir par etre coupe.

    Sans cela il reste eligible pour toujours et reprend un tour de cascade a
    chaque episode : exactement ce qui a ete observe sur uqload.
    """
    from engine.download import _host_breakers as HB

    _passe_ytdlp_sans_fichier(HB._FAILURE_THRESHOLD)

    assert HB.host_disponible("sibnet") is False


def test_le_disjoncteur_tient_encore_sous_le_seuil(_passe_ytdlp_sans_fichier):
    """Un echec isole ne coupe pas l'hote : le seuil existe pour ca."""
    from engine.download import _host_breakers as HB

    _passe_ytdlp_sans_fichier(HB._FAILURE_THRESHOLD - 1)

    assert HB.host_disponible("sibnet") is True
