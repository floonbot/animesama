"""Property-based tests (Hypothesis) — extension to more critical pure functions.

Same deterministic profile as tests/test_property_based.py (derandomize=True,
deadline=None) so the suite stays reproducible and never flaky. Targets the
crash-recovery dedup key, the legacy IPv4 SSRF decoder, the JS library/eps
extractors and the episode normaliser. No network/IO is touched.
"""

import ipaddress

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from engine.download._helpers import normaliser_episodes
from engine.download.queue import _item_identity
from engine.scraping.parser._base import _extraire_eps_arrays
from engine.utils.security import _ipv4_legacy

settings.register_profile(
    "determ",
    deadline=None,
    derandomize=True,
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("determ")

_jsonish = st.dictionaries(
    st.text(max_size=12),
    st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=20)),
    max_size=6,
)


@given(_jsonish)
def test_item_identity_is_key_order_independent(d):
    """Equal payloads yield equal identity regardless of key insertion order.

    This is the invariant the crash-recovery dedup relies on (restore() must not
    re-enqueue an item already present under a different key order)."""
    reordered = dict(reversed(list(d.items())))
    assert _item_identity(d) == _item_identity(reordered)


@given(_jsonish)
def test_item_identity_deterministic_and_str(d):
    """_item_identity is a pure deterministic string function."""
    a = _item_identity(d)
    assert isinstance(a, str)
    assert a == _item_identity(dict(d))


@given(st.dictionaries(st.text(max_size=8), st.sets(st.integers(), max_size=4), max_size=4))
def test_item_identity_never_raises_on_non_serialisable(d):
    """Non-JSON-serialisable values (sets) never crash the dedup key."""
    out = _item_identity(d)
    assert isinstance(out, str)


@given(st.ip_addresses(v=4))
def test_ipv4_legacy_dotted_round_trips_and_decimal_is_consistent(ip):
    """The dotted form always decodes back to ip; the bare-decimal form, when
    inet_aton accepts it at all, decodes to ip (never to a different address)."""
    assert _ipv4_legacy(str(ip)) == ip
    assert _ipv4_legacy(str(int(ip))) in (None, ip)


@given(st.text())
def test_ipv4_legacy_never_raises(s):
    """Arbitrary text (incl. embedded null bytes) yields None or an IPv4Address."""
    out = _ipv4_legacy(s)
    assert out is None or isinstance(out, ipaddress.IPv4Address)


def test_is_safe_url_never_crashes_on_null_or_control_host():
    """Regression: a null byte in the host must never raise (it crashed before the
    inet_aton/getaddrinfo ValueError fix); invalid hosts resolve to False."""
    from engine.utils.security import is_safe_url

    for url in ("http://\x00/x", "http://1.2.3.4\x00/x", "http://a\x00b.com/x"):
        assert isinstance(is_safe_url(url), bool)
    assert is_safe_url("http://\x00/x") is False
    assert is_safe_url("http://a\x00b.com/x") is False




@given(st.text())
def test_extraire_eps_arrays_returns_dict_of_lists(html):
    """_extraire_eps_arrays always returns a dict whose values are lists of str."""
    out = _extraire_eps_arrays(html)
    assert isinstance(out, dict)
    for key, val in out.items():
        assert isinstance(key, str)
        assert isinstance(val, list)
        assert all(isinstance(u, str) for u in val)


_episode = st.dictionaries(
    st.sampled_from(["titre", "nom", "saison", "episode", "url", "extra"]),
    st.one_of(st.none(), st.text(max_size=15), st.integers(min_value=-3, max_value=99)),
    max_size=5,
)


@given(st.one_of(st.lists(_episode, max_size=4), _episode))
def test_normaliser_episodes_structural_invariants(payload):
    """normaliser_episodes returns a list of dicts each carrying titre/saison/episode."""
    item = {"episodes": payload} if isinstance(payload, list) else {"ep": payload}
    out = normaliser_episodes(item)
    assert isinstance(out, list)
    for ep in out:
        assert isinstance(ep, dict)
        assert ep.get("titre")
        assert "saison" in ep
        assert "episode" in ep
