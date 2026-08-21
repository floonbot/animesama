"""Regressions from the exhaustive final sweep.

- engine/library/updates.py: invalider_cache_updates vide bien le cache 300 s.
- engine/auth/manager.py: keepalive must not KeyError on a stored cookie that
  lacks a "value" key (mirrors the defensive c.get() used for domain/path).
"""

import engine.auth.manager as mgr_mod
import engine.config.settings as cfg
from engine.library import updates


def test_updates_invalidate_vide_le_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    updates.invalider_cache_updates()
    updates._updates_tc.set({"animes": ["X"]})
    assert updates._updates_tc.get() is not None
    updates.invalider_cache_updates()
    assert updates._updates_tc.get() is None


def test_keepalive_cookie_without_value_does_not_crash(monkeypatch):
    monkeypatch.setattr(mgr_mod, "AuthStorage", lambda: object())
    mgr = mgr_mod.AuthManager()
    mgr._logged_in = True
    mgr.cookies = [{"name": "novalue"}, {"name": "sess", "value": "1"}]
    set_calls = []

    class _Jar:
        def set(self, name, value, **k):
            set_calls.append((name, value))

    class _Session:
        def __init__(self):
            self.headers = {}
            self.cookies = _Jar()

        def close(self):
            pass

    resp = mgr_mod.req.Response()
    resp.status_code = 200
    resp._content = b'{"logged_in": true}'

    sess = _Session()
    sess.get = lambda *a, **k: resp
    monkeypatch.setattr(mgr_mod.req, "Session", lambda: sess)

    assert mgr.keepalive_session() is True
    assert ("novalue", "") in set_calls
    assert ("sess", "1") in set_calls
