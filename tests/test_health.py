import asyncio
import collections
import json

from web.api.routes import health as health_mod
from web.api.routes.health import health


def test_health_shape():
    out = asyncio.run(health())
    assert out["ok"] is True
    assert out["version"]
    assert set(out["queue"]) == {"en_cours", "pending", "en_pause", "persistence"}
    assert set(out["engines"]) == {"nm3u8dl", "ytdlp", "ffmpeg"}
    assert "connected" in out["auth"]
    assert isinstance(out["browser"], bool)
    assert {"frozen", "chromium_bundled", "playwright_browsers_path"} <= set(out["runtime"])


def _fake_usage(total, used, free):
    U = collections.namedtuple("U", "total used free")
    return lambda p: U(total, used, free)


def test_health_disk_reports_free_total_used(monkeypatch):
    gb = 1024 ** 3
    monkeypatch.setattr(health_mod.shutil, "disk_usage", _fake_usage(200 * gb, 50 * gb, 150 * gb))
    out = asyncio.run(health())
    d = out["disk"]["downloads"]
    assert d["free_gb"] == 150.0
    assert d["total_gb"] == 200.0
    assert d["used_pct"] == 25


def test_health_disk_includes_temp(monkeypatch):
    gb = 1024 ** 3
    monkeypatch.setattr(health_mod.shutil, "disk_usage", _fake_usage(100 * gb, 40 * gb, 60 * gb))
    out = asyncio.run(health())
    t = out["disk"]["temp"]
    assert t["free_gb"] == 60.0
    assert t["total_gb"] == 100.0
    assert t["used_pct"] == 40


def test_health_disk_block_survives_usage_error(monkeypatch):
    def boom(_p):
        raise OSError("no disk")

    monkeypatch.setattr(health_mod.shutil, "disk_usage", boom)
    out = asyncio.run(health())
    assert out["disk"] == {}
    assert out["ok"] is True


def test_health_process_fields():
    out = asyncio.run(health())
    p = out["process"]
    assert isinstance(p["pid"], int)
    assert isinstance(p["uptime_s"], int)
    assert p["python"]
    assert p["platform"]


def test_health_process_includes_memory_and_threads_with_psutil():
    out = asyncio.run(health())
    p = out["process"]
    assert isinstance(p["memory_mb"], (int, float))
    assert p["memory_mb"] >= 0
    assert isinstance(p["threads"], int)
    assert p["threads"] >= 1
    assert "cpu_pct" in p


def test_health_process_survives_without_psutil(monkeypatch):
    monkeypatch.setattr(health_mod, "_PROC", None)
    out = asyncio.run(health())
    p = out["process"]
    assert "pid" in p
    assert "memory_mb" not in p
    assert out["ok"] is True


def test_health_sse_client_count_is_int():
    out = asyncio.run(health())
    assert isinstance(out["sse"]["clients"], int)


def test_health_auth_includes_cookie_count_and_keepalive(monkeypatch):
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_manager, "_logged_in", True)
    monkeypatch.setattr(auth_manager, "cookies", [{"name": "a", "value": "x"}, {"name": "b", "value": "y"}])
    out = asyncio.run(health())
    a = out["auth"]
    assert a["connected"] is True
    assert a["cookies"] == 2
    assert "keepalive" in a


def test_health_never_leaks_cookie_values(monkeypatch):
    from engine.auth.manager import auth_manager

    monkeypatch.setattr(auth_manager, "_logged_in", True)
    monkeypatch.setattr(auth_manager, "cookies", [{"name": "sess", "value": "SUPERSECRET"}])
    monkeypatch.setattr(auth_manager, "username", "john.doe@example.com")
    blob = json.dumps(asyncio.run(health()))
    assert "SUPERSECRET" not in blob
    assert "john.doe@example.com" not in blob

def test_health_runtime_block_reports_chromium():
    out = asyncio.run(health())
    rt = out["runtime"]
    assert set(rt) >= {"frozen", "chromium_bundled", "playwright_browsers_path"}
    assert isinstance(rt["frozen"], bool)
    assert isinstance(rt["chromium_bundled"], bool)


def test_health_runtime_reflects_bundled_chromium(monkeypatch):
    monkeypatch.setattr(health_mod, "_runtime_chromium_bundled", lambda: True)
    out = asyncio.run(health())
    assert out["runtime"]["chromium_bundled"] is True


def test_health_breakers_lists_open_and_half_open(monkeypatch):
    from engine.download import _host_breakers as hb

    monkeypatch.setattr(
        hb, "etat_breakers",
        lambda: {"down.tld": "open", "probing.tld": "half_open", "fine.tld": "closed"},
    )
    out = asyncio.run(health())
    b = out["breakers"]
    assert set(b) == {"open", "half_open"}
    assert b["open"] == ["down.tld"]
    assert b["half_open"] == ["probing.tld"]
    assert "fine.tld" not in b["open"]
    assert "fine.tld" not in b["half_open"]


def test_health_breakers_empty_when_all_closed(monkeypatch):
    from engine.download import _host_breakers as hb

    monkeypatch.setattr(hb, "etat_breakers", lambda: {"a.tld": "closed"})
    out = asyncio.run(health())
    assert out["breakers"] == {"open": [], "half_open": []}


def test_health_breakers_block_survives_error(monkeypatch):
    from engine.download import _host_breakers as hb

    def boom():
        raise RuntimeError("breakers down")

    monkeypatch.setattr(hb, "etat_breakers", boom)
    out = asyncio.run(health())
    assert "breakers" not in out
    assert out["ok"] is True


def test_health_registered_route():
    from fastapi.testclient import TestClient

    from web.api.app import create_app

    c = TestClient(create_app(), base_url="http://localhost")
    assert c.get("/api/health").status_code == 200
