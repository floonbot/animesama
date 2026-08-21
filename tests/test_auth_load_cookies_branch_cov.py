from engine.auth.storage import AuthStorage


def test_load_cookies_dict_without_cookies_key_returns_empty(monkeypatch):
    st = AuthStorage()
    monkeypatch.setattr(st, "load_session", lambda: {"username": "x"})
    assert st.load_cookies() == []


def test_load_cookies_non_list_cookies_returns_empty(monkeypatch):
    st = AuthStorage()
    monkeypatch.setattr(st, "load_session", lambda: {"cookies": "not-a-list"})
    assert st.load_cookies() == []


def test_load_cookies_returns_list_when_present(monkeypatch):
    st = AuthStorage()
    cookies = [{"name": "sid"}]
    monkeypatch.setattr(st, "load_session", lambda: {"cookies": cookies, "username": "u"})
    assert st.load_cookies() == cookies


def test_load_cookies_no_session_returns_empty(monkeypatch):
    st = AuthStorage()
    monkeypatch.setattr(st, "load_session", lambda: None)
    assert st.load_cookies() == []
