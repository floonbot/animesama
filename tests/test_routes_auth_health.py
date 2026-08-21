import asyncio
from unittest.mock import Mock

import pytest

WRITE_HEADERS = {"origin": "http://localhost:7843"}


@pytest.fixture(autouse=True)
def _reset_login_throttle(monkeypatch):
    import web.api.routes.auth as auth_mod

    snapshot = auth_mod._last_login_ts

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(auth_mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(auth_mod, "_last_login_ts", 0.0)
    monkeypatch.setattr(auth_mod.time, "time", lambda: 10_000.0)
    yield
    auth_mod._last_login_ts = snapshot


def test_status_logged_in_maps_manager_state(client, monkeypatch, logged_in):
    """A logged-in manager surfaces connected=True and its username verbatim."""
    monkeypatch.setattr(logged_in, "username", "alice", raising=False)

    r = client.get("/api/auth/status")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["username"] == "alice"


def test_status_manager_failure_degrades_to_disconnected(client, monkeypatch):
    """If reading the manager state raises, status degrades to a safe disconnected shape."""
    import engine.auth.manager as manager_mod

    class _Boom:
        @property
        def is_logged_in(self):
            raise RuntimeError("state corrupt")

    monkeypatch.setattr(manager_mod, "auth_manager", _Boom())

    r = client.get("/api/auth/status")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["username"] is None


def test_login_failure_result_forwarded(client, monkeypatch):
    """A backend rejection ({ok: False}) is forwarded verbatim with HTTP 200."""
    from engine.auth.manager import auth_manager

    async def _login(email, password):
        return {"ok": False, "message": "Identifiants incorrects"}

    monkeypatch.setattr(auth_manager, "login_async", _login)

    r = client.post(
        "/api/auth/login",
        headers=WRITE_HEADERS,
        json={"pseudo": "utilisateur_test", "password": "secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"] == "Identifiants incorrects"


def test_login_no_semaphore_returns_internal_error(client, monkeypatch):
    """When the asyncio semaphore is unavailable the route short-circuits without a backend call."""
    import web.api.routes.auth as auth_mod
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_mod, "_login_semaphore", lambda: None)
    login_async = Mock()
    monkeypatch.setattr(auth_manager, "login_async", login_async)

    r = client.post(
        "/api/auth/login",
        headers=WRITE_HEADERS,
        json={"pseudo": "utilisateur_test", "password": "secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"] == "Erreur interne (loop asyncio)"
    login_async.assert_not_called()


def test_login_backend_exception_degrades_to_internal_error(client, monkeypatch):
    """A raising backend login degrades to a structured internal-error dict, not a 500."""
    from engine.auth.manager import auth_manager

    async def _boom(email, password):
        raise RuntimeError("network down")

    monkeypatch.setattr(auth_manager, "login_async", _boom)

    r = client.post(
        "/api/auth/login",
        headers=WRITE_HEADERS,
        json={"pseudo": "utilisateur_test", "password": "secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"] == "Erreur interne pendant le login"


def test_login_throttle_advances_last_login_ts(client, monkeypatch):
    """A served login advances the throttle timestamp by the computed wait window."""
    import web.api.routes.auth as auth_mod
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_mod, "_last_login_ts", 10_000.0)

    async def _login(email, password):
        return {"ok": True, "message": "Connecté !", "username": "u"}

    monkeypatch.setattr(auth_manager, "login_async", _login)

    r = client.post(
        "/api/auth/login",
        headers=WRITE_HEADERS,
        json={"pseudo": "utilisateur_test", "password": "secret"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert auth_mod._last_login_ts == 10_000.0 + auth_mod._MIN_DELAI_LOGINS


def test_health_maps_queue_auth_browser_from_engine(client, monkeypatch):
    """The health route projects controlled engine state into its queue/auth/browser fields."""
    from engine.download import interceptor
    from engine.download.queue import queue

    monkeypatch.setattr(
        queue,
        "statut",
        lambda: {
            "en_cours": {"id": 1},
            "queue": ["a", "b", "c"],
            "en_pause": True,
        },
    )
    monkeypatch.setattr(queue, "_store", None)
    monkeypatch.setattr(interceptor, "_is_browser_alive", lambda b: True)
    monkeypatch.setattr(interceptor, "_browser", object(), raising=False)

    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_manager, "_logged_in", True)

    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"] == "2.0.0"
    assert body["queue"] == {"en_cours": True, "pending": 3, "en_pause": True, "persistence": False}
    assert body["auth"]["connected"] is True
    assert "cookies" in body["auth"]
    assert "keepalive" in body["auth"]
    assert body["browser"] is True


def test_health_queue_failure_omits_queue_field(client, monkeypatch):
    """A failing queue.statut() drops only the queue field while the rest of health survives."""
    from engine.download.queue import queue

    def _boom():
        raise RuntimeError("queue offline")

    monkeypatch.setattr(queue, "statut", _boom)

    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "queue" not in body
    assert "auth" in body
    assert "engines" in body


def test_health_browser_alive_false_maps_through(client, monkeypatch):
    """A dead browser is reported as browser=False rather than omitted."""
    from engine.download import interceptor

    monkeypatch.setattr(interceptor, "_is_browser_alive", lambda b: False)
    monkeypatch.setattr(interceptor, "_browser", None, raising=False)

    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["browser"] is False


def test_health_direct_coroutine_queue_pending_count(monkeypatch):
    """Calling the health coroutine directly counts pending queue entries by length."""
    from engine.download.queue import queue
    from web.api.routes.health import health

    monkeypatch.setattr(
        queue,
        "statut",
        lambda: {"en_cours": None, "queue": [1, 2], "en_pause": False},
    )
    monkeypatch.setattr(queue, "_store", None)

    out = asyncio.run(health())
    assert out["queue"] == {"en_cours": False, "pending": 2, "en_pause": False, "persistence": False}
