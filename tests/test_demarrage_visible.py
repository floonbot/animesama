"""Le demarrage doit parler : 11 fois dans le journal du poste, la fenetre s'est
fermee sur « Serveur non disponible apres 10s » sans que rien n'apparaisse a l'ecran.
"""

import sys
import threading
import time

import pytest

import desktop
import server


def _preparer_static(tmp_path, monkeypatch, *, bundle_avant_les_sources: bool):
    import engine.config.settings as st

    (tmp_path / "dist").mkdir()
    (tmp_path / "js" / "pages").mkdir(parents=True)
    bundle = tmp_path / "dist" / "app.js"
    source = tmp_path / "js" / "pages" / "library.js"

    if bundle_avant_les_sources:
        bundle.write_text("ancien", encoding="utf-8")
        source.write_text("neuf", encoding="utf-8")
        import os
        os.utime(source, (time.time() + 60, time.time() + 60))
    else:
        source.write_text("neuf", encoding="utf-8")
        bundle.write_text("frais", encoding="utf-8")
        import os
        os.utime(bundle, (time.time() + 60, time.time() + 60))

    monkeypatch.setattr(st, "STATIC_DIR", tmp_path)
    return bundle, source


def test_un_bundle_plus_vieux_que_les_sources_est_signale(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    _preparer_static(tmp_path, monkeypatch, bundle_avant_les_sources=True)

    motif = server.bundle_perime()

    assert "library.js" in motif


def test_un_bundle_a_jour_ne_dit_rien(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    _preparer_static(tmp_path, monkeypatch, bundle_avant_les_sources=False)

    assert server.bundle_perime() == ""


def test_le_paquet_ne_compare_pas_des_sources_qu_il_n_embarque_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    _preparer_static(tmp_path, monkeypatch, bundle_avant_les_sources=True)

    assert server.bundle_perime() == ""


def test_l_avertissement_de_bundle_perime_arrive_dans_les_logs(tmp_path, monkeypatch, caplog):
    monkeypatch.delattr(sys, "frozen", raising=False)
    _preparer_static(tmp_path, monkeypatch, bundle_avant_les_sources=True)

    with caplog.at_level("WARNING", logger="main"):
        server.avertir_si_bundle_perime()

    assert "npm run build" in caplog.text


@pytest.fixture
def port_muet(monkeypatch):
    """Une instance de l'application peut occuper 7843 sur le poste de dev :
    sans ce leurre, wait_for_server reussirait et les tests d'attente seraient nuls."""
    import socket

    def _refuse(*_a, **_k):
        raise OSError("refuse pour le test")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    faux_temps = {"t": 0.0}

    def _horloge():
        faux_temps["t"] += 1.0
        return faux_temps["t"]

    monkeypatch.setattr(server.time, "time", _horloge)
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)


def test_l_attente_s_interrompt_quand_la_fenetre_se_ferme(monkeypatch):
    """Le thread de rappel de pywebview n'est pas demon : sans sortie anticipee,
    fermer la fenetre laissait le processus vivre jusqu'au bout du budget."""
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail(
        "l'attente doit sortir avant meme de tenter la connexion"
    ))
    arret = threading.Event()
    arret.set()

    t0 = time.monotonic()
    ok = server.wait_for_server(timeout=30, arret=arret)

    assert ok is False
    assert time.monotonic() - t0 < 2.0


def test_l_attente_previent_pendant_qu_elle_dure(port_muet):
    appels: list = []

    server.wait_for_server(
        timeout=20, on_attente=lambda ecoule, total: appels.append((ecoule, total))
    )

    assert appels, "aucun signal d'attente emis"
    assert all(total == 20 for _e, total in appels)


def test_un_callback_d_attente_en_erreur_ne_casse_pas_le_demarrage(port_muet):
    def _boom(_ecoule, _total):
        raise RuntimeError("callback casse")

    assert server.wait_for_server(timeout=15, on_attente=_boom) is False


def test_le_serveur_mort_ne_livre_sa_cause(monkeypatch):
    """Sans cela, l'utilisateur ne voyait qu'un timeout nu la ou le port etait pris."""
    import web.api.app as app_mod

    def _explose():
        raise OSError("adresse déjà utilisée")

    monkeypatch.setattr(app_mod, "create_app", _explose)
    monkeypatch.setattr(server, "verifier_prerequis", lambda: [])
    try:
        server.start_server()

        assert "adresse déjà utilisée" in server.erreur_demarrage()
        assert "OSError" in server.erreur_demarrage()
    finally:
        server._erreur_demarrage = ""


def test_le_budget_est_bien_plus_large_pour_le_paquet(monkeypatch):
    """L'analyse antivirus d'un bundle de 1,2 Go depasse largement les 10 s d'origine."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    budget_paquet = desktop._budget_attente()
    monkeypatch.delattr(sys, "frozen", raising=False)
    budget_sources = desktop._budget_attente()

    assert budget_paquet >= 60.0
    assert budget_paquet > budget_sources > 10.0


def test_l_echec_nomme_la_cause_quand_elle_est_connue(monkeypatch):
    monkeypatch.setattr(server, "erreur_demarrage", lambda: "OSError : port occupé")

    assert "port occupé" in desktop._message_echec(120.0)


def test_l_echec_sans_cause_reste_actionnable(monkeypatch):
    monkeypatch.setattr(server, "erreur_demarrage", lambda: "")

    message = desktop._message_echec(120.0)

    assert "120" in message
    assert "port" in message


def test_l_echec_s_affiche_dans_la_fenetre_et_non_dans_un_fichier(monkeypatch):
    monkeypatch.setattr(server, "wait_for_server", lambda **k: False)
    monkeypatch.setattr(server, "erreur_demarrage", lambda: "")

    class _Fenetre:
        def __init__(self):
            self.html = ""
            self.url = ""

        def load_html(self, html):
            self.html = html

        def load_url(self, url):
            self.url = url

    fenetre = _Fenetre()
    desktop._rejoindre_serveur(fenetre, "http://127.0.0.1:7843", threading.Event())

    assert fenetre.url == ""
    assert "n'a pas pu démarrer" in fenetre.html
    assert desktop._CHEMIN_LOG in fenetre.html


def test_la_fenetre_rejoint_le_serveur_des_qu_il_repond(monkeypatch):
    monkeypatch.setattr(server, "wait_for_server", lambda **k: True)

    class _Fenetre:
        url = ""

        def load_url(self, url):
            self.url = url

        def load_html(self, html):  # pragma: no cover - ne doit pas etre appele
            raise AssertionError("page d'erreur affichee alors que le serveur repond")

    fenetre = _Fenetre()
    desktop._rejoindre_serveur(fenetre, "http://127.0.0.1:7843", threading.Event())

    assert fenetre.url == "http://127.0.0.1:7843"


def test_la_fermeture_pendant_l_attente_n_affiche_pas_d_erreur(monkeypatch):
    monkeypatch.setattr(server, "wait_for_server", lambda **k: False)
    arret = threading.Event()
    arret.set()

    class _Fenetre:
        def load_url(self, url):  # pragma: no cover
            raise AssertionError("navigation apres fermeture")

        def load_html(self, html):  # pragma: no cover
            raise AssertionError("erreur affichee dans une fenetre fermee")

    desktop._rejoindre_serveur(_Fenetre(), "http://127.0.0.1:7843", arret)


def test_aucune_boite_de_dialogue_hors_build_fenetre(monkeypatch):
    """En dev le message est deja lisible dans le terminal ; la boite ne sert que
    la ou sys.stderr part dans %TEMP%\\anime_sama_desktop.log."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("ANIMESAMA_NO_DIALOG", raising=False)

    assert desktop._peut_afficher_boite() is False


@pytest.mark.skipif(sys.platform != "win32", reason="boite de dialogue Windows")
def test_le_build_fenetre_affiche_une_boite_faute_de_console(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ANIMESAMA_NO_DIALOG", raising=False)

    assert desktop._peut_afficher_boite() is True


def test_la_fenetre_s_ouvre_avant_que_le_serveur_reponde(monkeypatch):
    """Le defaut d'origine : desktop.py sortait par sys.exit(1) sans jamais creer
    de fenetre, ce qui est indiscernable d'un blocage systeme."""
    monkeypatch.setattr(server, "wait_for_server", lambda *a, **k: False)
    monkeypatch.setattr(server, "_verifier_static_dir", lambda: True)
    monkeypatch.setattr(server, "purger_logs_nm3u8dl", lambda **k: None)
    monkeypatch.setattr(server, "start_server", lambda: None)
    monkeypatch.setattr(server, "restore_session", lambda: None)
    monkeypatch.setattr(server, "cancel_active_download", lambda: None)
    monkeypatch.setattr(server, "stop_server_gracefully", lambda: None)

    cree: dict = {}

    class _Signal:
        def __init__(self):
            self.abonnes: list = []

        def __iadd__(self, fn):
            self.abonnes.append(fn)
            return self

    class _Evenements:
        def __init__(self):
            self.closed = _Signal()

    class _Fenetre:
        def __init__(self):
            self.events = _Evenements()

    class _FauxWebview:
        @staticmethod
        def create_window(*a, **k):
            cree["kwargs"] = k
            cree["fenetre"] = _Fenetre()
            return cree["fenetre"]

        @staticmethod
        def start(*a, **k):
            cree["demarre"] = True

    monkeypatch.setitem(sys.modules, "webview", _FauxWebview)

    desktop.main()

    assert cree.get("demarre") is True
    assert "Démarrage d'Anime-Sama" in cree["kwargs"]["html"]
    assert cree["fenetre"].events.closed.abonnes, "fermeture non branchee sur l'arret"
