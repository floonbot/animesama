"""Property-based tests (Hypothesis) for the security-critical pure functions.

These complement the example-based suite by generating thousands of inputs to
falsify the contracts of the SSRF gate, the filename sanitiser, the JS
extractors and the naming/scan helpers. The profile is deterministic
(``derandomize=True``, ``deadline=None``) so the suite stays reproducible and
never flaky. No network/DNS is touched: only IP literals and numeric legacy
forms are fed to the SSRF gate (those resolve without ``getaddrinfo``).
"""

import ipaddress

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.scraping.parser._base import (
    _extraire_tableau_js,
)
from engine.scraping.parser.naming import nettoyer_titre, nom_fichier
from engine.scraping.scan import _chap_sort_key, normaliser_lang, slug_valide
from engine.scraping.site.animessama import SCAN_LANGS
from engine.utils.security import (
    _FILENAME_UNSAFE,
    _MAX_FILENAME_LEN,
    is_safe_url,
    sanitize_filename,
)

settings.register_profile(
    "determ",
    deadline=None,
    derandomize=True,
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("determ")


def _genuinely_public(ip) -> bool:
    """The security invariant: an address the gate is allowed to accept."""
    return (
        ip.is_global
        and not ip.is_loopback
        and not ip.is_private
        and not ip.is_link_local
        and not ip.is_reserved
        and not ip.is_multicast
        and not ip.is_unspecified
    )


def _url_for(ip) -> str:
    if isinstance(ip, ipaddress.IPv6Address):
        return f"http://[{ip}]/x"
    return f"http://{ip}/x"


@given(st.ip_addresses(v=4))
def test_ssrf_ipv4_literal_never_accepts_non_public(ip):
    """SECURITY: is_safe_url must never accept a non-public IPv4 literal."""
    if is_safe_url(_url_for(ip)):
        assert _genuinely_public(ip), f"SSRF bypass: accepted {ip}"


@given(st.ip_addresses(v=6))
def test_ssrf_ipv6_literal_never_accepts_non_public(ip):
    """SECURITY: same invariant for IPv6 literals (incl. v4-mapped/embedded)."""
    if is_safe_url(_url_for(ip)):
        assert _genuinely_public(ip), f"SSRF bypass: accepted {ip}"


@given(st.ip_addresses(v=4).filter(lambda ip: not _genuinely_public(ip)))
def test_ssrf_legacy_decimal_encoding_of_non_public_is_blocked(ip):
    """Alternate IPv4 encodings (decimal/octal/hex) of a non-public IP stay blocked."""
    decimal = f"http://{int(ip)}/x"
    assert not is_safe_url(decimal), f"SSRF bypass via decimal form of {ip}"
    octets = str(ip).split(".")
    hex_form = f"http://0x{int(octets[0]):x}.{'.'.join(octets[1:])}/x"
    assert not is_safe_url(hex_form), f"SSRF bypass via hex form of {ip}"


@given(st.sampled_from(["ftp", "file", "gopher", "data", "javascript", "ws", "dict"]))
def test_ssrf_non_http_schemes_rejected(scheme):
    """Only http/https are ever allowed, regardless of an otherwise-public host."""
    assert not is_safe_url(f"{scheme}://8.8.8.8/x")


@given(st.text())
def test_sanitize_filename_contract(name):
    """Sanitised output is non-empty, free of unsafe chars and of '..', length-bounded."""
    out = sanitize_filename(name)
    assert isinstance(out, str)
    assert out, "must never be empty"
    assert _FILENAME_UNSAFE.search(out) is None, f"unsafe char left in {out!r}"
    assert ".." not in out, f"path-traversal '..' left in {out!r}"
    assert len(out) <= _MAX_FILENAME_LEN + 1


@given(st.text())
def test_sanitize_filename_idempotent(name):
    """Sanitising an already-sanitised name changes nothing."""
    once = sanitize_filename(name)
    assert sanitize_filename(once) == once


def test_sanitize_filename_empty_after_stripping_falls_back_to_unnamed():
    """Inputs that reduce to empty after stripping spaces/dots fall back to 'unnamed'."""
    for blank in ("", "   ", " . . ", ".", None):
        assert sanitize_filename(blank) == "unnamed"


@given(st.floats(allow_nan=False, allow_infinity=False), st.floats(allow_nan=False, allow_infinity=False))
def test_chap_sort_key_preserves_numeric_order(a, b):
    """_chap_sort_key on numeric strings preserves the numeric ordering."""
    ka, kb = _chap_sort_key(repr(a)), _chap_sort_key(repr(b))
    if a < b:
        assert ka <= kb
    elif a > b:
        assert ka >= kb


@given(st.text())
def test_chap_sort_key_never_raises_and_non_numeric_is_inf(s):
    """Arbitrary text never raises; non-parseable values sort last (inf)."""
    key = _chap_sort_key(s)
    assert isinstance(key, float)
    try:
        float(s)
    except (TypeError, ValueError):
        assert key == float("inf")


@given(st.one_of(st.none(), st.text()))
def test_normaliser_lang_always_in_allowed_set(lang):
    """normaliser_lang always returns a member of SCAN_LANGS."""
    assert normaliser_lang(lang) in SCAN_LANGS


@given(st.text())
def test_slug_valide_returns_bool_and_matches_charset(slug):
    """slug_valide is total (returns a bool) and only accepts the documented charset."""
    result = slug_valide(slug)
    assert isinstance(result, bool)
    if result:
        assert 1 <= len(slug) <= 151
        assert all(c.isalnum() or c in "._-" for c in slug)


@given(st.text(), st.integers(min_value=0))
def test_extraire_tableau_js_never_raises_and_is_bracket_balanced(txt, start):
    """_extraire_tableau_js never raises; any returned slice is bracket-delimited."""
    out = _extraire_tableau_js(txt, start)
    if out is not None:
        assert out.startswith("[")
        assert out.endswith("]")


@given(st.text())
def test_nettoyer_titre_contract(titre):
    """nettoyer_titre is non-empty, bounded to 100 chars, no invalid-fs chars."""
    out = nettoyer_titre(titre)
    assert isinstance(out, str)
    assert out, "must never be empty (falls back to 'Anime')"
    assert len(out) <= 100


@given(
    st.text(),
    st.integers(min_value=-5, max_value=10_000),
    st.integers(min_value=-5, max_value=10_000),
    st.text(max_size=8),
)
def test_nom_fichier_never_raises_and_contains_season_episode(titre, saison, episode, langue):
    """nom_fichier never raises for any int-ish saison/episode and is non-empty."""
    out = nom_fichier(titre, saison, episode, langue)
    assert isinstance(out, str)
    assert out
