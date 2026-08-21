import sys
import webbrowser

import pytest

import desktop


def _stub_server(monkeypatch, *, deja_actif: bool) -> None:
    monkeypatch.setattr(desktop.server, "wait_for_server", lambda *a, **k: deja_actif)
    monkeypatch.setattr(desktop.server, "_verifier_static_dir", lambda *a, **k: True)
    monkeypatch.setattr(desktop.server, "purger_logs_nm3u8dl", lambda *a, **k: None)
    monkeypatch.setattr(desktop.server, "start_server", lambda *a, **k: None)
    monkeypatch.setattr(desktop.server, "restore_session", lambda *a, **k: None)
    monkeypatch.setattr(desktop.server, "cancel_active_download", lambda *a, **k: None)
    monkeypatch.setattr(desktop.server, "stop_server_gracefully", lambda *a, **k: None)


def test_main_without_pywebview_exits_and_never_opens_system_browser(monkeypatch):
    """Sans pywebview, l'app de bureau échoue proprement (exit 1) sans ouvrir le navigateur système."""
    _stub_server(monkeypatch, deja_actif=True)

    opened: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: opened.append(a))
    monkeypatch.setitem(sys.modules, "webview", None)

    with pytest.raises(SystemExit) as exc:
        desktop.main()

    assert exc.value.code == 1
    assert opened == []


def test_main_opens_pywebview_window_when_available(monkeypatch):
    """Avec pywebview présent, l'app ouvre une fenêtre webview (jamais le navigateur système)."""
    _stub_server(monkeypatch, deja_actif=True)

    calls: dict = {}

    class _FakeWebview:
        @staticmethod
        def create_window(*a, **k):
            calls["create"] = (a, k)

        @staticmethod
        def start(*a, **k):
            calls["start"] = True

    monkeypatch.setitem(sys.modules, "webview", _FakeWebview)
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: pytest.fail("navigateur système ouvert"))

    desktop.main()

    assert "create" in calls
    assert calls.get("start") is True
