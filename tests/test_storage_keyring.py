import logging
import sys
import types

import pytest

from engine.auth import storage


@pytest.fixture(autouse=True)
def _snapshot_keyring_modules():
    sentinel = object()
    saved_keyring = sys.modules.get("keyring", sentinel)
    saved_errors = sys.modules.get("keyring.errors", sentinel)
    yield
    for name, saved in (("keyring", saved_keyring), ("keyring.errors", saved_errors)):
        if saved is sentinel:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = saved


class _PasswordDeleteError(Exception):
    pass


def _install_fake_keyring(*, get=None, set_=None, delete=None):
    errors_mod = types.ModuleType("keyring.errors")
    errors_mod.PasswordDeleteError = _PasswordDeleteError

    kr_mod = types.ModuleType("keyring")
    if get is not None:
        kr_mod.get_password = get
    if set_ is not None:
        kr_mod.set_password = set_
    if delete is not None:
        kr_mod.delete_password = delete
    kr_mod.errors = errors_mod

    sys.modules["keyring"] = kr_mod
    sys.modules["keyring.errors"] = errors_mod
    return kr_mod, errors_mod


def test_kr_get_returns_stored_value():
    calls = []

    def _get(app, user):
        calls.append((app, user))
        return "stored-secret"

    _install_fake_keyring(get=_get)
    assert storage._kr_get("alice") == "stored-secret"
    assert calls == [(storage.KEYRING_APP, "alice")]


def test_kr_get_returns_none_and_logs_on_exception(caplog):
    def _get(app, user):
        raise OSError("backend down")

    _install_fake_keyring(get=_get)
    with caplog.at_level(logging.WARNING, logger="engine.auth.storage"):
        result = storage._kr_get("bob")
    assert result is None
    msgs = [r.getMessage() for r in caplog.records if r.name == "engine.auth.storage"]
    assert any("get_password" in m and "bob" in m and "backend down" in m for m in msgs)


def test_kr_get_returns_none_and_logs_on_import_failure(caplog):
    class _AttrRaises(types.ModuleType):
        def __getattr__(self, name):
            raise ImportError("no real keyring backend")

    sys.modules["keyring"] = _AttrRaises("keyring")
    with caplog.at_level(logging.WARNING, logger="engine.auth.storage"):
        result = storage._kr_get("carol")
    assert result is None
    msgs = [r.getMessage() for r in caplog.records if r.name == "engine.auth.storage"]
    assert any("get_password" in m and "carol" in m for m in msgs)


def test_kr_set_stores_value():
    calls = []

    def _set(app, user, value):
        calls.append((app, user, value))

    _install_fake_keyring(set_=_set)
    storage._kr_set("dave", "pw123")
    assert calls == [(storage.KEYRING_APP, "dave", "pw123")]


def test_kr_set_swallows_and_logs_on_exception(caplog):
    def _set(app, user, value):
        raise RuntimeError("write refused")

    _install_fake_keyring(set_=_set)
    with caplog.at_level(logging.WARNING, logger="engine.auth.storage"):
        storage._kr_set("erin", "pw")
    msgs = [r.getMessage() for r in caplog.records if r.name == "engine.auth.storage"]
    assert any("set_password" in m and "erin" in m and "write refused" in m for m in msgs)


def test_kr_delete_deletes():
    calls = []

    def _delete(app, user):
        calls.append((app, user))

    _install_fake_keyring(delete=_delete)
    storage._kr_delete("frank")
    assert calls == [(storage.KEYRING_APP, "frank")]


def test_kr_delete_swallows_password_delete_error_silently(caplog):
    def _delete(app, user):
        raise _PasswordDeleteError("not present")

    _install_fake_keyring(delete=_delete)
    with caplog.at_level(logging.WARNING, logger="engine.auth.storage"):
        storage._kr_delete("grace")
    msgs = [r.getMessage() for r in caplog.records if r.name == "engine.auth.storage"]
    assert not any("delete_password" in m for m in msgs)


def test_kr_delete_swallows_and_logs_other_exception(caplog):
    def _delete(app, user):
        raise OSError("locked")

    _install_fake_keyring(delete=_delete)
    with caplog.at_level(logging.WARNING, logger="engine.auth.storage"):
        storage._kr_delete("heidi")
    msgs = [r.getMessage() for r in caplog.records if r.name == "engine.auth.storage"]
    assert any("delete_password" in m and "heidi" in m and "locked" in m for m in msgs)


def test_kr_delete_logs_on_import_failure(caplog):
    class _AttrRaises(types.ModuleType):
        def __getattr__(self, name):
            raise ImportError("no real keyring backend")

    sys.modules["keyring"] = _AttrRaises("keyring")
    with caplog.at_level(logging.WARNING, logger="engine.auth.storage"):
        storage._kr_delete("ivan")
    msgs = [r.getMessage() for r in caplog.records if r.name == "engine.auth.storage"]
    assert any("delete_password" in m and "ivan" in m for m in msgs)
