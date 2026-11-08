"""Veille des nouveaux episodes et notifications Windows natives.

WebView2 refuse d'office l'API Notification du web (mesure du 07/11/2026) : les
notifications partent du serveur, et la veille ne signale chaque episode qu'une
fois.
"""

import asyncio
import json
import subprocess

import pytest

from engine.library import veille


def _ep(n, saison=1):
    return {"url": f"https://site/catalogue/x/saison{saison}/vostfr?ep={n}", "saison": saison,
            "episode": n, "titre": "X", "langue": "VOSTFR"}


def _resultat(*animes, total=None):
    return {"animes": list(animes), "checked_at": 1,
            "total_nouveaux": total if total is not None else sum(len(a["nouveaux_episodes"]) for a in animes)}


def _anime(nom, eps, listes=("favoris",)):
    return {"nom": nom, "url": f"https://site/catalogue/{nom}", "listes": list(listes),
            "nouveaux_count": len(eps), "nouveaux_episodes": eps}


@pytest.fixture
def env(tmp_path, monkeypatch):
    reglages = {"veille_nouveautes": True, "veille_auto_dl": False, "notifications": True}
    monkeypatch.setattr(veille, "_ETAT_FICHIER", tmp_path / "veille.json")
    monkeypatch.setattr("engine.config.user_settings.load_settings", lambda: dict(reglages))

    class _Auth:
        is_logged_in = True

    monkeypatch.setattr("engine.auth.manager.auth_manager", _Auth())
    resultats: list[dict] = []

    async def _check(refresh=False):
        assert refresh is True
        return resultats.pop(0)

    monkeypatch.setattr("engine.library.updates.check_updates_async", _check)
    evenements: list[tuple] = []
    monkeypatch.setattr("web.api.routes.sse.emit", lambda t, d: evenements.append((t, d)))
    toasts: list[tuple] = []
    monkeypatch.setattr("engine.utils.notifications.notifier", lambda t, c="": toasts.append((t, c)))
    files: list[dict] = []

    async def _ajouter(item):
        files.append(item)
        return {"ok": True}

    from engine.services.download_service import download_service
    monkeypatch.setattr(download_service, "ajouter_episode", _ajouter)
    return {"reglages": reglages, "resultats": resultats, "evenements": evenements,
            "toasts": toasts, "files": files}


def test_un_episode_n_est_signale_qu_une_fois(env):
    env["resultats"] += [
        _resultat(_anime("A", [_ep(5)])),
        _resultat(_anime("A", [_ep(5), _ep(6)])),
    ]
    b1 = asyncio.run(veille.un_tour())
    b2 = asyncio.run(veille.un_tour())

    assert (b1["total"], b2["total"]) == (1, 1)
    assert b2["total_en_attente"] == 2
    assert [t for t, _ in env["toasts"]] == ["🆕 1 nouvel épisode", "🆕 1 nouvel épisode"]
    assert env["toasts"][0][1] == "A (1)"


def test_rien_de_neuf_met_a_jour_la_pastille_sans_notifier(env):
    env["resultats"] += [_resultat(_anime("A", [_ep(5)])), _resultat(_anime("A", [_ep(5)]))]
    asyncio.run(veille.un_tour())
    bilan = asyncio.run(veille.un_tour())

    assert bilan["total"] == 0 and bilan["total_en_attente"] == 1
    assert len(env["toasts"]) == 1
    assert [t for t, _ in env["evenements"]] == ["nouveautes", "nouveautes"]


def test_auto_dl_ne_prend_que_la_watchlist_et_une_seule_fois(env):
    env["reglages"]["veille_auto_dl"] = True
    a = _anime("A", [_ep(5)], listes=("favoris", "watchlist"))
    b = _anime("B", [_ep(2)], listes=("favoris",))
    env["resultats"] += [_resultat(a, b), _resultat(a, b)]

    bilan = asyncio.run(veille.un_tour())
    asyncio.run(veille.un_tour())

    assert bilan["en_file"] == 1
    assert [f["episodes"][0]["url"] for f in env["files"]] == [_ep(5)["url"]]
    assert "1 ajouté au téléchargement" in env["toasts"][0][1]


def test_veille_coupee_ou_sans_session_ne_touche_pas_au_site(env, monkeypatch):
    env["reglages"]["veille_nouveautes"] = False
    assert asyncio.run(veille.un_tour()) is None

    env["reglages"]["veille_nouveautes"] = True

    class _Hors:
        is_logged_in = False

    monkeypatch.setattr("engine.auth.manager.auth_manager", _Hors())
    assert asyncio.run(veille.un_tour()) is None
    assert env["resultats"] == []  # check_updates jamais appele


def test_echec_du_site_compte_comme_une_tentative(env):
    env["resultats"].append({"animes": [], "total_nouveaux": 0, "erreur": True})
    assert asyncio.run(veille.un_tour()) == {"echec": True}
    assert not veille._ETAT_FICHIER.exists()


def test_la_liste_retenue_ne_grossit_pas(env):
    env["resultats"] += [_resultat(_anime("A", [_ep(5), _ep(6)])), _resultat(_anime("A", [_ep(6)]))]
    asyncio.run(veille.un_tour())
    asyncio.run(veille.un_tour())  # l'episode 5 a ete telecharge entre-temps
    assert json.loads(veille._ETAT_FICHIER.read_text(encoding="utf-8"))["signales"] == [_ep(6)["url"]]


def test_boucle_n_attend_pas_une_minute_apres_un_echec(monkeypatch, tmp_path):
    # Un echec doit repousser au prochain intervalle, pas a la minute suivante.
    monkeypatch.setattr(veille, "_ETAT_FICHIER", tmp_path / "veille.json")
    monkeypatch.setattr(veille, "_DELAI_DEMARRAGE_S", 0)
    monkeypatch.setattr(veille, "_PAS_S", 0)
    monkeypatch.setattr("engine.config.user_settings.load_settings",
                        lambda: {"veille_nouveautes": True, "veille_intervalle_h": 6})
    tours = []

    async def _tour():
        tours.append(1)
        return {"echec": True}

    monkeypatch.setattr(veille, "un_tour", _tour)

    async def _scenario():
        tache = asyncio.create_task(veille.boucle())
        for _ in range(40):  # load_settings et l'etat passent par des threads
            await asyncio.sleep(0.005)
        tache.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tache

    asyncio.run(_scenario())
    assert len(tours) == 1


def test_intervalle_hors_liste_retombe_sur_le_defaut():
    assert veille.intervalle_h({"veille_intervalle_h": 7}) == 6
    assert veille.intervalle_h({"veille_intervalle_h": "x"}) == 6
    assert veille.intervalle_h({"veille_intervalle_h": 12}) == 12


def test_jamais_demarree_sous_pytest():
    assert veille.demarrer() is None


# ── Notifications ────────────────────────────────────────────────────────────

def test_toast_echappe_le_xml_et_les_apostrophes():
    from engine.utils import notifications as n

    xml = n._xml_toast("A <b> & 'c'", "d", silencieux=True)
    assert "&lt;b&gt; &amp;" in xml and '<audio silent="true"/>' in xml
    script = n._script(xml)
    assert "''c''" in script and n.AUMID in script


def test_notifier_respecte_le_reglage_et_pytest(monkeypatch):
    from engine.utils import notifications as n

    lancees = []
    monkeypatch.setattr(n.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: lancees.append(k)})())
    monkeypatch.setattr(n, "_declarer_aumid", lambda: True)
    assert n.notifier("t") is False  # sous pytest : jamais

    monkeypatch.setattr(n, "_desactive", lambda: False)
    monkeypatch.setattr("engine.config.user_settings.load_settings", lambda: {"notifications": False})
    assert n.notifier("t") is False
    monkeypatch.setattr("engine.config.user_settings.load_settings",
                        lambda: {"notifications": True, "son_notif": False})
    assert n.notifier("t", "c") is (n.os.name == "nt")
    if lancees:
        assert lancees[0]["args"] == ("t", "c", True)


def test_echec_powershell_journalise_sans_lever(monkeypatch, caplog):
    from engine.utils import notifications as n

    monkeypatch.setattr(n.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"Element not found"))
    with caplog.at_level("INFO", logger="engine.utils.notifications"):
        n._envoyer("t", "c", False)
    assert "Element not found" in caplog.text


def test_fin_d_anime_notifie_seulement_un_succes(monkeypatch):
    from web.api.routes import sse

    toasts = []
    monkeypatch.setattr("engine.utils.notifications.notifier", lambda t, c="": toasts.append((t, c)))
    sse._notifier_fin_anime("anime_done", {"titre": "X", "succes": 0})
    sse._notifier_fin_anime("anime_done", {"titre": "X", "succes": 3, "annule": True})
    sse._notifier_fin_anime("episode_done", {"titre": "X", "succes": 1})
    sse._notifier_fin_anime("anime_done", {"titre": "X", "succes": 3})
    assert toasts == [("🎌 Anime terminé", "X — 3 épisodes téléchargés")]


def test_reglages_valident_l_intervalle(client, monkeypatch, tmp_path):
    import engine.config.logging_setup  # noqa: F401 — installe log.success, lu par la route
    from engine.config import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "user_settings.json")
    origine = {"Origin": "http://localhost:7843"}
    assert client.post("/api/settings", json={"veille_intervalle_h": 5}, headers=origine).json()["ok"] is False
    r = client.post("/api/settings", json={"veille_intervalle_h": 12, "veille_auto_dl": True},
                    headers=origine).json()
    assert r["ok"] and r["settings"]["veille_intervalle_h"] == 12 and r["settings"]["veille_auto_dl"]
    g = client.get("/api/settings").json()
    assert isinstance(g["notifs_coupees_par_windows"], bool)
    assert "notifs_coupees_par_windows" not in json.loads((tmp_path / "user_settings.json").read_text("utf-8"))
