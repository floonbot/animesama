from pathlib import Path

import pytest

import engine.config.settings as settings
import engine.config.user_settings as user_settings
from engine.domain.exceptions import UnsafeUrlError
from engine.utils import security, url_pin


def _fake_getaddrinfo(records):
    def _inner(host, port, *a, **k):
        return [(2, 1, 6, "", (ip, 0)) for ip in records]

    return _inner


def _boom_getaddrinfo(*a, **k):
    raise AssertionError("getaddrinfo ne doit pas etre appele pour une cible litterale")


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """Redirige DATA_DIR vers tmp_path pour isoler user_settings."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "user_settings.json")
    return tmp_path


class TestPinTargetGaps:
    def test_empty_url_raises_unsafe(self):
        """pin_target('') leve UnsafeUrlError avant tout traitement."""
        with pytest.raises(UnsafeUrlError):
            security.pin_target("")

    def test_malformed_url_raises_unsafe(self):
        """Un URL dont urlparse echoue (IPv6 non ferme) leve UnsafeUrlError."""
        with pytest.raises(UnsafeUrlError):
            security.pin_target("http://[::1")

    def test_missing_hostname_raises_unsafe(self):
        """pin_target('http://') sans hostname leve UnsafeUrlError."""
        with pytest.raises(UnsafeUrlError):
            security.pin_target("http://")

    def test_blocked_host_raises_unsafe(self):
        """Un host de la liste BLOCKED_HOSTS leve UnsafeUrlError."""
        with pytest.raises(UnsafeUrlError):
            security.pin_target("http://localhost/x")

    def test_private_ip_literal_raises_unsafe(self):
        """Une IP RFC1918 litterale leve UnsafeUrlError sans DNS."""
        with pytest.raises(UnsafeUrlError):
            security.pin_target("http://192.168.1.1/x")

    def test_legacy_global_ipv4_pins_to_decoded_ip(self, monkeypatch):
        """Un entier IPv4 herite global renvoie (hostname, IP pointee) sans DNS."""
        monkeypatch.setattr(security.socket, "getaddrinfo", _boom_getaddrinfo)
        assert security.pin_target("http://16843009/v") == ("16843009", "1.1.1.1")

    def test_invalid_sockaddr_records_yield_lookup_error(self, monkeypatch):
        """Si tous les enregistrements DNS ont une IP invalide, pin_target leve LookupError."""
        monkeypatch.setattr(
            security.socket, "getaddrinfo", _fake_getaddrinfo(["not-an-ip", "still-bad"])
        )
        with pytest.raises(LookupError):
            security.pin_target("http://weird.test/x")

    def test_invalid_then_valid_record_skips_to_safe_ip(self, monkeypatch):
        """Un enregistrement invalide est ignore et le suivant valide est retourne."""
        monkeypatch.setattr(
            security.socket, "getaddrinfo", _fake_getaddrinfo(["bad-ip", "8.8.8.8"])
        )
        assert security.pin_target("http://mixed.test/x") == ("mixed.test", "8.8.8.8")


class TestUrlPin:
    def test_nested_pin_restores_previous_ip(self):
        """Un pin imbrique restaure l'IP precedente a la sortie, puis purge a la fin."""
        host = "nested-pin.test"
        assert url_pin._pins().get(host) is None
        with url_pin.pin_connection(host, "1.1.1.1"):
            assert url_pin._pins().get(host) == "1.1.1.1"
            with url_pin.pin_connection(host, "2.2.2.2"):
                assert url_pin._pins().get(host) == "2.2.2.2"
            assert url_pin._pins().get(host) == "1.1.1.1"
        assert url_pin._pins().get(host) is None

    def test_install_patches_create_connection_when_not_installed(self, monkeypatch):
        """install() remplace create_connection lors du premier appel effectif."""
        import urllib3.util.connection as uc

        saved_installed = url_pin._installed
        saved_cc = uc.create_connection
        try:
            url_pin._installed = False
            url_pin.install()
            assert url_pin._installed is True
            assert uc.create_connection is not saved_cc
        finally:
            url_pin._installed = saved_installed
            uc.create_connection = saved_cc
        assert uc.create_connection is saved_cc

    def test_install_is_noop_when_already_installed(self):
        """Un second install() ne change rien quand le patch est deja en place."""
        import urllib3.util.connection as uc

        saved_installed = url_pin._installed
        saved_cc = uc.create_connection
        try:
            url_pin._installed = True
            assert url_pin.install() is None
            assert uc.create_connection is saved_cc
        finally:
            url_pin._installed = saved_installed
            uc.create_connection = saved_cc

    def test_install_inner_double_check_returns_without_patching(self, monkeypatch):
        """url_pin.py:22 — _installed passe a True pendant l'acquisition du verrou → return interne."""
        import urllib3.util.connection as uc

        saved_installed = url_pin._installed
        saved_cc = uc.create_connection

        class _LockSetsInstalled:
            def __enter__(self):
                url_pin._installed = True
                return self

            def __exit__(self, *exc):
                return False

        try:
            url_pin._installed = False
            monkeypatch.setattr(url_pin, "_install_lock", _LockSetsInstalled())
            url_pin.install()
            assert uc.create_connection is saved_cc
        finally:
            url_pin._installed = saved_installed
            uc.create_connection = saved_cc


class TestSettingsFallbacks:
    def test_has_chromium_dir_oserror_returns_false(self):
        """_has_chromium_dir renvoie False si l'inspection du dossier leve OSError."""

        class _Boom:
            def is_dir(self):
                raise OSError("denied")

            def glob(self, _pattern):
                return []

        assert settings._has_chromium_dir(_Boom()) is False

    def test_configure_bundled_bin_path_oserror_returns_false(self, monkeypatch):
        """_configure_bundled_bin_path renvoie False si is_dir leve OSError en mode frozen."""

        def _boom(self, *a, **k):
            raise OSError("denied")

        monkeypatch.setattr(Path, "is_dir", _boom)
        env: dict[str, str] = {}
        assert settings._configure_bundled_bin_path(Path("/bundle"), True, env) is False
        assert "PATH" not in env


class TestUserSettingsChmodFallback:
    def test_save_settings_survives_chmod_oserror(self, tmp_path, monkeypatch):
        """save_settings renvoie True meme si os.chmod du fichier temporaire echoue."""
        monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "s.json")

        def _boom(*a, **k):
            raise OSError("chmod denied")

        monkeypatch.setattr(user_settings.os, "chmod", _boom)
        assert user_settings.save_settings({"qualite": "720"}) is True
        assert (tmp_path / "s.json").exists()


