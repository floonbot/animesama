"""C13.0 — « Trop de tentatives, réessaie dans quelques secondes » n'apprend rien.

Le limiteur reserve un creneau d'une seconde par appel : `_last_login_ts` avance
dans le futur a chaque fois, donc `wait_s` grandit d'une seconde par tentative
et franchit `_MAX_WAIT_LOGIN` a la sixieme. Le refus est legitime — c'est une
file d'attente bornee — mais il doit dire combien de temps attendre.
"""

import asyncio

import pytest
from fastapi import HTTPException

import web.api.routes.auth as auth_mod
from web.api.models import LoginRequest


@pytest.fixture(autouse=True)
def _horloge_figee(monkeypatch):
    monkeypatch.setattr(auth_mod, "_last_login_ts", 0.0)
    monkeypatch.setattr(auth_mod.time, "time", lambda: 10_000.0)
    monkeypatch.setattr(auth_mod.asyncio, "sleep", _ne_dors_pas)
    sem = auth_mod._login_sem
    obj, loop = sem._obj, sem._loop
    yield
    sem._obj, sem._loop = obj, loop


async def _ne_dors_pas(_s):
    return None


@pytest.fixture(autouse=True)
def _login_instantane(monkeypatch):
    from engine.auth.manager import auth_manager

    async def _ok(pseudo, password):
        return {"ok": True, "username": pseudo}

    monkeypatch.setattr(auth_manager, "login_async", _ok)


def _tenter():
    return asyncio.run(auth_mod.login(LoginRequest(pseudo="x", password="y")))


def test_la_sixieme_tentative_rapprochee_est_refusee():
    for _ in range(5):
        assert _tenter()["ok"] is True

    with pytest.raises(HTTPException) as exc:
        _tenter()
    assert exc.value.status_code == 429


def test_le_refus_annonce_une_duree_chiffree():
    for _ in range(5):
        _tenter()
    with pytest.raises(HTTPException) as exc:
        _tenter()

    detail = exc.value.detail
    assert "quelques secondes" not in detail
    # La file se vide au bout de `_last_login_ts - now`, soit wait_s - 1 s.
    assert "4 s" in detail or "4 secondes" in detail, detail


def test_le_refus_porte_un_entete_retry_after():
    for _ in range(5):
        _tenter()
    with pytest.raises(HTTPException) as exc:
        _tenter()

    headers = exc.value.headers or {}
    assert headers.get("Retry-After") == "4"


def test_un_refus_n_allonge_pas_la_file():
    for _ in range(5):
        _tenter()
    avant = auth_mod._last_login_ts
    with pytest.raises(HTTPException):
        _tenter()
    assert auth_mod._last_login_ts == avant


def test_une_tentative_isolee_passe_sans_attente():
    assert _tenter()["ok"] is True
    assert auth_mod._last_login_ts == 10_000.0
