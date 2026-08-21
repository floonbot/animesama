import asyncio
import json

import pytest

import engine.auth.manager as auth_mod
import engine.config.settings as settings_mod
import engine.library.scanner as scanner_mod
import engine.library.updates as updates
import engine.scraping.scraper as scraper_mod


@pytest.fixture(autouse=True)
def _reset_updates_cache():
    updates.invalider_cache_updates()
    yield
    updates.invalider_cache_updates()


def _run(coro):
    return asyncio.run(coro)


def _async_return(value):
    async def _coro(*args, **kwargs):
        return value

    return _coro


def _patch_boundaries(
    monkeypatch,
    *,
    logged_in=True,
    librairie=None,
    favoris=None,
    episodes_by_url=None,
):
    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", logged_in)
    monkeypatch.setattr(
        scanner_mod,
        "scan_librairie_sync",
        lambda: librairie if librairie is not None else {"animes": []},
    )
    monkeypatch.setattr(
        scraper_mod, "get_favorites_async", _async_return(favoris if favoris is not None else [])
    )

    table = episodes_by_url or {}

    async def _get_eps(url, force_refresh=False):
        return table.get(url, {"episodes": []})

    monkeypatch.setattr(scraper_mod, "get_episodes_async", _get_eps)


def test_not_logged_in_returns_non_connecte(monkeypatch):
    _patch_boundaries(monkeypatch, logged_in=False)
    out = _run(updates.check_updates_async())
    assert out["non_connecte"] is True
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0
    assert updates._updates_tc.get() is None


def test_nouveaux_episodes_respectent_la_langue_locale(monkeypatch):
    librairie = {
        "animes": [
            {
                "nom": "Overlord",
                "saisons": [{"nom": "Saison 01", "episodes": [
                    {"nom": "Overlord - S01E012 VOSTFR"},
                    {"nom": "Overlord - S01E013 VOSTFR"},
                ]}],
            }
        ]
    }
    favoris = [{"nom": "Overlord", "url": "http://site/ovl"}]
    episodes = {
        "http://site/ovl": {
            "titre": "Overlord",
            "episodes": [
                {"saison": 1, "episode": 14, "url": "vf14", "langue": "VF"},
                {"saison": 1, "episode": 14, "url": "vo14", "langue": "VOSTFR"},
                {"saison": 1, "episode": 15, "url": "vf15", "langue": "VF"},
                {"saison": 1, "episode": 15, "url": "vo15", "langue": "VOSTFR"},
            ],
        }
    }
    _patch_boundaries(
        monkeypatch, logged_in=True, librairie=librairie, favoris=favoris, episodes_by_url=episodes
    )
    out = _run(updates.check_updates_async())
    eps = out["animes"][0]["nouveaux_episodes"]
    assert {e["langue"] for e in eps} == {"VOSTFR"}
    assert {e["url"] for e in eps} == {"vo14", "vo15"}


def test_saison_index_desalignee_ne_cree_pas_de_fausse_nouveaute(monkeypatch):
    librairie = {
        "animes": [
            {
                "nom": "Mushoku Tensei",
                "saisons": [
                    {"nom": "Saison 03", "episodes": [
                        {"nom": "Mushoku Tensei - S03E024 VOSTFR"},
                    ]},
                    {"nom": "Saison 2 Partie 1", "episodes": [
                        {"nom": "Mushoku Tensei - Saison 2 Partie 1 - E012 VOSTFR"},
                    ]},
                ],
            }
        ]
    }
    favoris = [{"nom": "Mushoku Tensei", "url": "http://site/mt"}]
    episodes = {
        "http://site/mt": {
            "titre": "Mushoku Tensei",
            "episodes": [
                {"saison": 5, "episode": 24, "url": "s3e24", "langue": "VOSTFR", "saison_nom": "Saison 3"},
                {"saison": 2, "episode": 12, "url": "s2e12", "langue": "VOSTFR", "saison_nom": "Saison 2 Partie 1"},
            ],
        }
    }
    _patch_boundaries(
        monkeypatch, logged_in=True, librairie=librairie, favoris=favoris, episodes_by_url=episodes
    )
    out = _run(updates.check_updates_async())
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0


def test_vraies_nouveautes_detectees_par_dossier(monkeypatch):
    librairie = {
        "animes": [
            {"nom": "Mushoku Tensei", "saisons": [
                {"nom": "Saison 03", "episodes": [{"nom": "Mushoku Tensei - S03E024 VOSTFR"}]},
            ]}
        ]
    }
    favoris = [{"nom": "Mushoku Tensei", "url": "http://site/mt"}]
    episodes = {
        "http://site/mt": {
            "titre": "Mushoku Tensei",
            "episodes": [
                {"saison": 5, "episode": 25, "url": "s3e25", "langue": "VOSTFR", "saison_nom": "Saison 3"},
                {"saison": 6, "episode": 1, "url": "s4e1", "langue": "VOSTFR", "saison_nom": "Saison 4"},
            ],
        }
    }
    _patch_boundaries(
        monkeypatch, logged_in=True, librairie=librairie, favoris=favoris, episodes_by_url=episodes
    )
    out = _run(updates.check_updates_async())
    urls = {e["url"] for e in out["animes"][0]["nouveaux_episodes"]}
    assert "s3e25" in urls
    assert "s4e1" in urls


def test_cache_hit_returns_cached_without_calling_boundaries(monkeypatch):
    sentinel = {"animes": ["CACHED"], "total_nouveaux": 99, "checked_at": 1}
    updates._updates_tc.set(sentinel)

    def _boom():
        raise AssertionError("scan must not be called on cache hit")

    monkeypatch.setattr(scanner_mod, "scan_librairie_sync", _boom)
    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", True)

    out = _run(updates.check_updates_async(refresh=False))
    assert out is sentinel


def test_refresh_true_bypasses_cache(monkeypatch):
    updates._updates_tc.set({"animes": ["STALE"], "total_nouveaux": 5, "checked_at": 1})
    _patch_boundaries(monkeypatch, logged_in=True, librairie={"animes": []})

    out = _run(updates.check_updates_async(refresh=True))
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0
    assert "checked_at" in out


def test_empty_library_returns_empty_and_caches(monkeypatch):
    _patch_boundaries(monkeypatch, logged_in=True, librairie={"animes": []})
    out = _run(updates.check_updates_async())
    assert out == {"animes": [], "total_nouveaux": 0, "checked_at": out["checked_at"]}
    assert updates._updates_tc.get() is out


def test_no_favorite_match_returns_empty(monkeypatch):
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie={"animes": [{"nom": "Mystery Show", "saisons": []}]},
        favoris=[{"nom": "Totally Different", "url": "http://x/other"}],
    )
    out = _run(updates.check_updates_async())
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0
    assert updates._updates_tc.get() is out


def test_favorite_match_without_url_is_skipped(monkeypatch):
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie={"animes": [{"nom": "Demon Slayer", "saisons": []}]},
        favoris=[{"nom": "Demon Slayer", "url": ""}],
    )
    out = _run(updates.check_updates_async())
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0


def test_new_episode_same_season_detected(monkeypatch):
    librairie = {
        "animes": [
            {
                "nom": "Demon Slayer",
                "saisons": [{"nom": "Saison 01", "episodes": [{"nom": "Demon Slayer - S01E005"}]}],
            }
        ]
    }
    favoris = [{"nom": "Démon Slayer", "url": "http://site/ds", "image": "http://img/ds.png"}]
    episodes = {
        "http://site/ds": {
            "titre": "Demon Slayer",
            "episodes": [
                {"saison": 1, "episode": 5, "url": "u5", "langue": "VOSTFR"},
                {"saison": 1, "episode": 6, "url": "u6", "langue": "VOSTFR"},
                {"saison": 1, "episode": 7, "url": "u7", "langue": "VOSTFR"},
            ],
        }
    }
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie=librairie,
        favoris=favoris,
        episodes_by_url=episodes,
    )
    out = _run(updates.check_updates_async())
    assert out["total_nouveaux"] == 2
    assert len(out["animes"]) == 1
    anime = out["animes"][0]
    assert anime["nom"] == "Demon Slayer"
    assert anime["url"] == "http://site/ds"
    assert anime["image"] == "http://img/ds.png"
    assert anime["nouveaux_count"] == 2
    eps = anime["nouveaux_episodes"]
    assert [e["episode"] for e in eps] == [6, 7]
    assert {e["type"] for e in eps} == {"nouveau"}
    assert eps[0]["url"] == "u6"
    assert eps[0]["titre"] == "Demon Slayer"


def test_nouvelle_saison_emet_tous_les_episodes(monkeypatch):
    librairie = {
        "animes": [
            {
                "nom": "OnePiece",
                "saisons": [{"nom": "Saison 01", "episodes": [{"nom": "OnePiece - S01E010"}]}],
            }
        ]
    }
    favoris = [{"nom": "OnePiece", "url": "http://site/op"}]
    episodes = {
        "http://site/op": {
            "episodes": [
                {"saison": 2, "episode": 1, "url": "s2e1", "langue": "VF", "saison_nom": "Saison 2"},
                {"saison": 2, "episode": 3, "url": "s2e3", "langue": "VF", "saison_nom": "Saison 2"},
                {"saison": 2, "episode": 2, "url": "s2e2", "langue": "VF", "saison_nom": "Saison 2"},
            ]
        }
    }
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie=librairie,
        favoris=favoris,
        episodes_by_url=episodes,
    )
    out = _run(updates.check_updates_async())
    anime = out["animes"][0]
    assert anime["nouveaux_count"] == 3
    eps = anime["nouveaux_episodes"]
    assert {e["url"] for e in eps} == {"s2e1", "s2e2", "s2e3"}
    assert all(e["type"] == "nouvelle_saison" for e in eps)
    assert anime["nom"] == "OnePiece"


def test_no_new_episodes_anime_excluded(monkeypatch):
    librairie = {
        "animes": [
            {
                "nom": "UpToDate",
                "saisons": [{"nom": "Saison 01", "episodes": [{"nom": "UpToDate - S01E012"}]}],
            }
        ]
    }
    favoris = [{"nom": "UpToDate", "url": "http://site/utd"}]
    episodes = {
        "http://site/utd": {
            "episodes": [
                {"saison": 1, "episode": 11, "url": "a"},
                {"saison": 1, "episode": 12, "url": "b"},
            ]
        }
    }
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie=librairie,
        favoris=favoris,
        episodes_by_url=episodes,
    )
    out = _run(updates.check_updates_async())
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0


def test_episode_zero_or_negative_ignored(monkeypatch):
    librairie = {
        "animes": [
            {"nom": "Edge", "saisons": [{"episodes": [{"nom": "Edge - S01E003"}]}]}
        ]
    }
    favoris = [{"nom": "Edge", "url": "http://site/edge"}]
    episodes = {
        "http://site/edge": {
            "episodes": [
                {"saison": 1, "episode": 0, "url": "zero"},
                {"saison": 1, "episode": None, "url": "none"},
            ]
        }
    }
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie=librairie,
        favoris=favoris,
        episodes_by_url=episodes,
    )
    out = _run(updates.check_updates_async())
    assert out["animes"] == []


def test_online_empty_episodes_excluded(monkeypatch):
    librairie = {
        "animes": [
            {"nom": "Empty", "saisons": [{"episodes": [{"nom": "Empty - S01E001"}]}]}
        ]
    }
    favoris = [{"nom": "Empty", "url": "http://site/empty"}]
    episodes = {"http://site/empty": {"episodes": []}}
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie=librairie,
        favoris=favoris,
        episodes_by_url=episodes,
    )
    out = _run(updates.check_updates_async())
    assert out["animes"] == []


def test_get_episodes_exception_is_swallowed(monkeypatch):
    librairie = {
        "animes": [
            {"nom": "Boom", "saisons": [{"episodes": [{"nom": "Boom - S01E001"}]}]}
        ]
    }
    favoris = [{"nom": "Boom", "url": "http://site/boom"}]
    _patch_boundaries(monkeypatch, logged_in=True, librairie=librairie, favoris=favoris)

    async def _raise(url, force_refresh=False):
        raise RuntimeError("network down")

    monkeypatch.setattr(scraper_mod, "get_episodes_async", _raise)
    out = _run(updates.check_updates_async())
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0
    assert "erreur" not in out


def test_results_sorted_and_total_aggregated(monkeypatch):
    librairie = {
        "animes": [
            {"nom": "Zeta", "saisons": [{"nom": "Saison 01", "episodes": [{"nom": "Zeta - S01E001"}]}]},
            {"nom": "Alpha", "saisons": [{"nom": "Saison 01", "episodes": [{"nom": "Alpha - S01E001"}]}]},
        ]
    }
    favoris = [
        {"nom": "Zeta", "url": "http://site/zeta"},
        {"nom": "Alpha", "url": "http://site/alpha"},
    ]
    episodes = {
        "http://site/zeta": {
            "episodes": [{"saison": 1, "episode": 2, "url": "z2"}]
        },
        "http://site/alpha": {
            "episodes": [
                {"saison": 1, "episode": 2, "url": "a2"},
                {"saison": 1, "episode": 3, "url": "a3"},
            ]
        },
    }
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie=librairie,
        favoris=favoris,
        episodes_by_url=episodes,
    )
    out = _run(updates.check_updates_async())
    assert [a["nom"] for a in out["animes"]] == ["Alpha", "Zeta"]
    assert out["total_nouveaux"] == 3


def test_exception_rule_filters_episode(monkeypatch, tmp_path):
    librairie = {
        "animes": [
            {"nom": "Filtered", "saisons": [{"episodes": [{"nom": "Filtered - S01E005"}]}]}
        ]
    }
    favoris = [{"nom": "Filtered", "url": "http://site/filtered"}]
    episodes = {
        "http://site/filtered": {
            "episodes": [
                {"saison": 1, "episode": 6, "url": "e6"},
                {"saison": 1, "episode": 7, "url": "e7"},
            ]
        }
    }
    ignore_file = tmp_path / "ignore_updates.json"
    ignore_file.write_text(
        json.dumps({"Filtered": {"episodes_ignores": {"1": [6]}}}), encoding="utf-8"
    )
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    _patch_boundaries(
        monkeypatch,
        logged_in=True,
        librairie=librairie,
        favoris=favoris,
        episodes_by_url=episodes,
    )
    out = _run(updates.check_updates_async())
    anime = out["animes"][0]
    assert anime["nouveaux_count"] == 1
    assert anime["nouveaux_episodes"][0]["episode"] == 7


def test_top_level_exception_returns_erreur(monkeypatch):
    monkeypatch.setattr(auth_mod.auth_manager, "_logged_in", True)

    def _explode():
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(scanner_mod, "scan_librairie_sync", _explode)
    monkeypatch.setattr(scraper_mod, "get_favorites_async", _async_return([]))

    out = _run(updates.check_updates_async())
    assert out["erreur"] is True
    assert out["animes"] == []
    assert out["total_nouveaux"] == 0


def test_charger_exceptions_missing_file_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    assert updates.charger_exceptions_updates() == {}


def test_charger_exceptions_non_dict_returns_empty(monkeypatch, tmp_path):
    (tmp_path / "ignore_updates.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    assert updates.charger_exceptions_updates() == {}


def test_charger_exceptions_normalises_keys_and_drops_non_dict_rules(monkeypatch, tmp_path):
    payload = {
        "Démon Slayer Saison 2": {"saisons_ignorees": [3]},
        "Bad Entry": "not-a-dict",
    }
    (tmp_path / "ignore_updates.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    out = updates.charger_exceptions_updates()
    assert out == {"demon slayer": {"saisons_ignorees": [3]}}


def test_charger_exceptions_invalid_json_returns_empty(monkeypatch, tmp_path):
    (tmp_path / "ignore_updates.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    assert updates.charger_exceptions_updates() == {}
