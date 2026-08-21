import json

import pytest

import engine.config.settings as settings
from engine.auth import storage
from engine.auth.storage import AuthStorage


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    kr: dict[str, str] = {}

    def _get(username: str):
        return kr.get(username)

    def _set(username: str, value: str) -> None:
        kr[username] = value

    def _delete(username: str) -> None:
        kr.pop(username, None)

    monkeypatch.setattr(storage, "_kr_get", _get)
    monkeypatch.setattr(storage, "_kr_set", _set)
    monkeypatch.setattr(storage, "_kr_delete", _delete)
    monkeypatch.setattr(storage, "COOKIES_FILE", tmp_path / "cookies.enc")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    yield kr


@pytest.fixture
def kr(_isolate):
    return _isolate


def test_le_stockage_ne_lit_pas_le_data_dir_reel(tmp_path):
    assert settings.DATA_DIR == tmp_path
    assert storage._cookies_file() == storage.COOKIES_FILE


def test_save_then_load_credentials():
    st = AuthStorage()
    st.save_credentials("john@example.com", "s3cr3t")
    assert st.load_credentials() == {"email": "john@example.com", "password": "s3cr3t"}


def test_load_credentials_none_when_password_missing(kr):
    st = AuthStorage()
    kr[storage.EMAIL_KEY_NAME] = "john@example.com"
    assert st.load_credentials() is None


def test_load_credentials_none_when_email_missing(kr):
    st = AuthStorage()
    kr[storage.PASSWORD_KEY_NAME] = "s3cr3t"
    assert st.load_credentials() is None


def test_save_credentials_stored_in_keyring(kr):
    st = AuthStorage()
    st.save_credentials("a@b.com", "pw")
    assert kr[storage.EMAIL_KEY_NAME] == "a@b.com"
    assert kr[storage.PASSWORD_KEY_NAME] == "pw"


def test_save_cookies_round_trip_via_load_session(kr):
    st = AuthStorage()
    cookies = [{"name": "sid", "value": "abc"}, {"name": "x", "value": "y"}]
    st.save_cookies(cookies, "user")
    assert storage.FERNET_KEY_NAME in kr
    assert storage.COOKIES_FILE.exists()
    on_disk = storage.COOKIES_FILE.read_text(encoding="utf-8")
    assert "sid" not in on_disk
    assert st.load_session() == {"cookies": cookies, "username": "user"}


def test_save_cookies_real_fernet_encryption_decryptable(kr):
    from cryptography.fernet import Fernet

    st = AuthStorage()
    st.save_cookies([{"name": "c"}], "u")
    raw = storage.COOKIES_FILE.read_text(encoding="utf-8")
    plain = Fernet(kr[storage.FERNET_KEY_NAME].encode()).decrypt(raw.encode()).decode()
    assert json.loads(plain) == {"cookies": [{"name": "c"}], "username": "u"}


def test_save_cookies_restricts_file_permissions(kr, monkeypatch):
    import os

    chmod_calls: list[tuple[str, int]] = []
    real_chmod = os.chmod

    def _spy(path, mode, *a, **k):
        chmod_calls.append((str(path), mode))
        return real_chmod(path, mode, *a, **k)

    monkeypatch.setattr(os, "chmod", _spy)
    st = AuthStorage()
    st.save_cookies([{"name": "sid", "value": "abc"}], "user")
    assert any(mode == 0o600 for _, mode in chmod_calls)


def test_load_cookies_wrapper_returns_list():
    st = AuthStorage()
    cookies = [{"name": "sid", "value": "abc"}]
    st.save_cookies(cookies, "user")
    assert st.load_cookies() == cookies


def test_load_cookies_empty_when_no_session():
    st = AuthStorage()
    assert st.load_cookies() == []


def test_load_session_none_when_file_absent():
    st = AuthStorage()
    assert not storage.COOKIES_FILE.exists()
    assert st.load_session() is None


def test_load_session_none_on_empty_file():
    st = AuthStorage()
    storage.COOKIES_FILE.write_text("", encoding="utf-8")
    assert st.load_session() is None


def test_load_session_none_on_whitespace_only_file():
    st = AuthStorage()
    storage.COOKIES_FILE.write_text("   \n  ", encoding="utf-8")
    assert st.load_session() is None


def test_load_session_none_on_corrupt_content():
    st = AuthStorage()
    storage.COOKIES_FILE.write_text("not-a-valid-fernet-token", encoding="utf-8")
    assert st.load_session() is None


def test_load_session_none_when_oversize(monkeypatch):
    """An otherwise-valid token is rejected solely by the size guard (isolated from decrypt failure)."""
    st = AuthStorage()
    token = storage._encrypt(json.dumps({"cookies": [{"name": "sid"}], "username": "u"}))
    storage.COOKIES_FILE.write_text(token, encoding="utf-8")
    monkeypatch.setattr(storage, "COOKIES_FILE_MAX_SIZE", len(token.encode("utf-8")) - 1)
    assert st.load_session() is None


def test_load_session_same_token_loads_under_default_max():
    """The same token loads successfully when the size guard does not trip — proves the guard is the cause."""
    st = AuthStorage()
    token = storage._encrypt(json.dumps({"cookies": [{"name": "sid"}], "username": "u"}))
    storage.COOKIES_FILE.write_text(token, encoding="utf-8")
    assert st.load_session() == {"cookies": [{"name": "sid"}], "username": "u"}


def test_load_session_legacy_list_payload(kr):
    st = AuthStorage()
    storage.COOKIES_FILE.write_text(
        storage._encrypt(json.dumps([{"name": "old"}, {"name": "old2"}])),
        encoding="utf-8",
    )
    assert st.load_session() == {"cookies": [{"name": "old"}, {"name": "old2"}], "username": ""}


def test_load_session_none_when_more_than_1000_cookies(kr):
    st = AuthStorage()
    big = [{"i": i} for i in range(1001)]
    storage.COOKIES_FILE.write_text(
        storage._encrypt(json.dumps({"cookies": big, "username": "u"})),
        encoding="utf-8",
    )
    assert st.load_session() is None


def test_load_session_exactly_1000_cookies_ok(kr):
    st = AuthStorage()
    big = [{"i": i} for i in range(1000)]
    st.save_cookies(big, "u")
    s = st.load_session()
    assert s is not None
    assert len(s["cookies"]) == 1000


def test_load_session_none_on_non_dict_non_list_payload(kr):
    st = AuthStorage()
    storage.COOKIES_FILE.write_text(
        storage._encrypt(json.dumps("just-a-string")),
        encoding="utf-8",
    )
    assert st.load_session() is None


def test_clear_removes_file():
    st = AuthStorage()
    st.save_cookies([{"name": "x"}], "u")
    assert storage.COOKIES_FILE.exists()
    st.clear()
    assert not storage.COOKIES_FILE.exists()


def test_clear_when_file_absent_is_noop():
    st = AuthStorage()
    assert not storage.COOKIES_FILE.exists()
    st.clear()
    assert not storage.COOKIES_FILE.exists()


def test_clear_all_removes_file_and_keyring_entries(kr):
    st = AuthStorage()
    st.save_credentials("a@b.com", "pw")
    st.save_cookies([{"name": "x"}], "u")
    assert storage.COOKIES_FILE.exists()
    assert storage.EMAIL_KEY_NAME in kr
    assert storage.PASSWORD_KEY_NAME in kr
    assert storage.FERNET_KEY_NAME in kr
    st.clear_all()
    assert not storage.COOKIES_FILE.exists()
    assert storage.EMAIL_KEY_NAME not in kr
    assert storage.PASSWORD_KEY_NAME not in kr
    assert storage.FERNET_KEY_NAME not in kr


def test_get_fernet_no_create_raises_when_absent(kr):
    assert storage.FERNET_KEY_NAME not in kr
    with pytest.raises(RuntimeError):
        storage._get_fernet(allow_create=False)


def test_get_fernet_create_generates_and_stores_key(kr):
    assert storage.FERNET_KEY_NAME not in kr
    f = storage._get_fernet(allow_create=True)
    assert storage.FERNET_KEY_NAME in kr
    token = f.encrypt(b"hello")
    assert f.decrypt(token) == b"hello"


def test_save_cookies_when_encrypt_raises_leaves_no_files(monkeypatch):
    st = AuthStorage()

    def _boom(_text: str) -> str:
        raise RuntimeError("nope")

    monkeypatch.setattr(storage, "_encrypt", _boom)
    st.save_cookies([{"name": "x"}], "u")
    assert not storage.COOKIES_FILE.exists()
    assert not storage.COOKIES_FILE.with_suffix(".enc.tmp").exists()
