import pytest

from engine.domain.exceptions import UnsafeUrlError
from engine.scraping import http_client
from engine.utils import security


def _fake_getaddrinfo(records):
    def _inner(host, port, *a, **k):
        return [(2, 1, 6, "", (ip, 0)) for ip in records]
    return _inner


class TestAlternateIpv4Encodings:
    @pytest.mark.parametrize(
        "host",
        ["2130706433", "127.1", "0177.0.0.1", "0x7f.0.0.1"],
    )
    def test_legacy_loopback_encodings_blocked_even_if_dns_says_public(self, host, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8"]))
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url(f"http://{host}/stream.m3u8")

    def test_decimal_zero_is_blocked(self, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8"]))
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url("http://0/")

    def test_legacy_global_encoding_is_allowed(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("getaddrinfo ne doit pas etre appele pour une IPv4 litterale")

        monkeypatch.setattr(security.socket, "getaddrinfo", _boom)
        url = "http://16843009/video"
        assert security.validate_external_url(url) == url


class TestIsSafeUrlCataloguePrefix:
    @pytest.mark.parametrize("path", ["/catalogue", "/catalogue/one-piece/saison1/vostfr?ep=1", "/catalogue?x=1"])
    def test_legit_catalogue_paths_allowed(self, path):
        assert http_client._is_safe_url(path) is True

    @pytest.mark.parametrize("path", ["/cataloguex", "/catalogue-evil/x", "/cataloguexyz/../etc"])
    def test_prefix_lookalikes_rejected(self, path):
        assert http_client._is_safe_url(path) is False


class TestBlockedHostsAndSchemes:
    @pytest.mark.parametrize(
        "host",
        ["localhost", "0.0.0.0", "metadata.google.internal", "169.254.169.254"],
    )
    def test_blocked_hosts(self, host):
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url(f"http://{host}/x")

    @pytest.mark.parametrize("scheme", ["ftp", "file", "gopher", "javascript", "data"])
    def test_non_http_schemes_rejected(self, scheme):
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url(f"{scheme}://example.com/x")

    @pytest.mark.parametrize("url", ["", "   ", "http://", "https:///path"])
    def test_empty_or_hostless_rejected(self, url):
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url(url)

    def test_scheme_and_host_case_are_normalized(self, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8"]))
        url = "HTTP://Example.COM/Path"
        assert security.validate_external_url(url) == url

    def test_userinfo_does_not_bypass_host_check(self, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8"]))
        assert security.is_safe_url("http://localhost@example.com/x") is True
        assert security.is_safe_url("http://example.com@localhost/x") is False


class TestEmbeddedIpv4InIpv6:
    @pytest.mark.parametrize(
        "host",
        [
            "64:ff9b::7f00:1",
            "64:ff9b::a00:1",
            "64:ff9b::a9fe:a9fe",
            "64:ff9b::c0a8:1",
            "64:ff9b::808:808",
        ],
    )
    def test_nat64_embedded_ipv4_blocked(self, host, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("getaddrinfo ne doit pas etre appele pour une IP litterale")

        monkeypatch.setattr(security.socket, "getaddrinfo", _boom)
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url(f"http://[{host}]/x")

    @pytest.mark.parametrize(
        "host",
        ["::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254"],
    )
    def test_ipv4_mapped_private_or_loopback_blocked(self, host, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("getaddrinfo ne doit pas etre appele pour une IP litterale")

        monkeypatch.setattr(security.socket, "getaddrinfo", _boom)
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url(f"http://[{host}]/x")


class TestPrivateAndLiteralIps:
    @pytest.mark.parametrize(
        "host",
        ["10.0.0.1", "172.16.0.1", "172.31.255.255", "192.168.1.1", "127.0.0.1"],
    )
    def test_private_ipv4_literals_blocked(self, host):
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url(f"http://{host}/x")

    @pytest.mark.parametrize("host", ["[::1]", "[fc00::1]", "[fe80::1]"])
    def test_private_ipv6_literals_blocked(self, host):
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url(f"http://{host}/x")

    def test_link_local_ipv4_blocked_via_classification(self):
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url("http://169.254.0.1/x")

    @pytest.mark.parametrize("host", ["172.15.0.1", "172.32.0.1", "8.8.8.8"])
    def test_global_ipv4_literals_allowed_without_dns(self, host, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("getaddrinfo ne doit pas etre appele pour une IP litterale")

        monkeypatch.setattr(security.socket, "getaddrinfo", _boom)
        url = f"http://{host}/v"
        assert security.validate_external_url(url) == url

    def test_global_ipv6_literal_allowed(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("getaddrinfo ne doit pas etre appele pour une IP litterale")

        monkeypatch.setattr(security.socket, "getaddrinfo", _boom)
        url = "http://[2606:4700:4700::1111]/v"
        assert security.validate_external_url(url) == url


class TestDnsResolution:
    def test_host_resolving_to_private_is_blocked(self, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["127.0.0.1"]))
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url("http://rebind.test/x")

    def test_block_when_any_resolved_record_is_private(self, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8", "10.0.0.1"]))
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url("http://rebind.test/x")

    def test_public_resolution_allowed(self, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8"]))
        url = "http://public.test/x"
        assert security.validate_external_url(url) == url

    def test_unresolvable_host_blocked(self, monkeypatch):
        import socket as _socket

        def _raise(*a, **k):
            raise _socket.gaierror("nope")

        monkeypatch.setattr(security.socket, "getaddrinfo", _raise)
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url("http://nx.test/x")

    def test_no_usable_ip_blocked(self, monkeypatch):
        def _bad(host, port, *a, **k):
            return [(2, 1, 6, "", ("not-an-ip", 0))]

        monkeypatch.setattr(security.socket, "getaddrinfo", _bad)
        with pytest.raises(UnsafeUrlError):
            security.validate_external_url("http://weird.test/x")


class TestPinTarget:
    def test_literal_global_ipv4_returns_itself(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("getaddrinfo ne doit pas etre appele pour une IP litterale")

        monkeypatch.setattr(security.socket, "getaddrinfo", _boom)
        assert security.pin_target("http://8.8.8.8/v") == ("8.8.8.8", "8.8.8.8")

    def test_hostname_returns_resolved_safe_ip(self, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8"]))
        assert security.pin_target("https://cdn.test/x") == ("cdn.test", "8.8.8.8")

    def test_rebinding_to_private_raises_unsafe(self, monkeypatch):
        monkeypatch.setattr(security.socket, "getaddrinfo", _fake_getaddrinfo(["10.0.0.1"]))
        with pytest.raises(UnsafeUrlError):
            security.pin_target("http://rebind.test/x")

    def test_unresolvable_raises_lookup_not_unsafe(self, monkeypatch):
        import socket as _socket

        def _raise(*a, **k):
            raise _socket.gaierror("nope")

        monkeypatch.setattr(security.socket, "getaddrinfo", _raise)
        with pytest.raises(LookupError):
            security.pin_target("http://nx.test/x")

    def test_bad_scheme_raises_unsafe(self):
        with pytest.raises(UnsafeUrlError):
            security.pin_target("file:///etc/passwd")


class TestSanitizeFilename:
    @pytest.mark.parametrize("bad", ['a/b', 'a\\b', 'a:b', 'a*b', 'a?b', 'a"b', 'a<b>c', 'a|b'])
    def test_unsafe_chars_replaced(self, bad):
        out = security.sanitize_filename(bad)
        assert all(c not in out for c in '/\\:*?"<>|')

    def test_path_traversal_neutralized(self):
        assert ".." not in security.sanitize_filename("../../etc/passwd")

    @pytest.mark.parametrize("name", ["CON", "NUL", "COM1", "LPT9", "con.txt"])
    def test_windows_reserved_names_prefixed(self, name):
        assert security.sanitize_filename(name).startswith("_")

    def test_empty_and_non_str_become_unnamed(self):
        assert security.sanitize_filename("") == "unnamed"
        assert security.sanitize_filename(None) == "unnamed"

    def test_length_is_capped(self):
        assert len(security.sanitize_filename("x" * 500)) <= 200

    def test_trailing_dots_and_spaces_stripped(self):
        assert security.sanitize_filename("name.   ") == "name"

    def test_double_dot_sequence_becomes_underscores_before_strip(self):
        assert security.sanitize_filename("name...   ") == "name__"


class TestCookiesCacheKey:
    def test_empty_is_anonymous(self):
        assert http_client._cookies_cache_key([]) == "anonymous"
        assert http_client._cookies_cache_key(None) == "anonymous"

    def test_order_independent_and_deterministic(self):
        a = [{"name": "s", "value": "1"}, {"name": "x", "value": "2"}]
        b = [{"name": "x", "value": "2"}, {"name": "s", "value": "1"}]
        assert http_client._cookies_cache_key(a) == http_client._cookies_cache_key(b)
        assert http_client._cookies_cache_key(a) != "anonymous"

    def test_nameless_and_non_dict_entries_ignored(self):
        only_valid = http_client._cookies_cache_key([{"name": "s", "value": "1"}])
        noisy = http_client._cookies_cache_key(
            [{"name": "s", "value": "1"}, {"value": "x"}, "garbage", {"name": ""}]
        )
        assert noisy == only_valid
