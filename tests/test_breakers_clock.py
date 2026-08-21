import asyncio

import pytest

from engine.download import _host_breakers as hb
from engine.download import _rate_limiter as rl
from engine.download._domain_strategy import lecteur_url_valide, strategie_lecteur
from engine.utils import circuit_breaker as cbmod
from engine.utils.circuit_breaker import CircuitBreaker, CircuitState


def _run(coro):
    return asyncio.run(coro)


class FakeMonotonic:
    """Controllable replacement for time.monotonic with a mutable cursor."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


async def _boom():
    raise ValueError("boom")


@pytest.fixture(autouse=True)
def _isolate_globals(monkeypatch):
    """Clear shared module globals before AND after every test."""
    hb._breakers.clear()
    rl._domain_last_access.clear()
    yield
    hb._breakers.clear()
    rl._domain_last_access.clear()


@pytest.fixture
def cb_clock(monkeypatch):
    """Install a controllable fake clock on the circuit_breaker module."""
    clock = FakeMonotonic()
    monkeypatch.setattr(cbmod.time, "monotonic", clock)
    return clock


def _trip_open(cb, n):
    for _ in range(n):
        with pytest.raises(ValueError):
            _run(cb.call(_boom))


def test_recovery_timeout_flips_to_half_open_then_closed_on_probe(cb_clock):
    """At exactly recovery_timeout, the next call probes and a success closes the breaker."""
    cb = CircuitBreaker("h", failure_threshold=2, recovery_timeout=30.0)
    _trip_open(cb, 2)
    assert cb.state == CircuitState.OPEN

    cb_clock.now += 30.0

    probed = {"called": False}

    async def probe():
        probed["called"] = True
        assert cb.state == CircuitState.HALF_OPEN
        return "ok"

    result = _run(cb.call(probe))

    assert probed["called"] is True
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED


def test_probe_success_resets_failure_counter(cb_clock):
    """A successful HALF_OPEN probe zeroes the accumulated failure count."""
    cb = CircuitBreaker("h", failure_threshold=2, recovery_timeout=30.0)
    _trip_open(cb, 2)
    cb_clock.now += 30.0

    async def ok():
        return 1

    _run(cb.call(ok))

    assert cb._failures == 0


def test_half_open_probe_failure_reopens(cb_clock):
    """A failing probe re-opens the circuit and refreshes the cooldown anchor."""
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)
    assert cb.state == CircuitState.OPEN

    cb_clock.now += 30.0

    with pytest.raises(ValueError):
        _run(cb.call(_boom))

    assert cb.state == CircuitState.OPEN


def test_half_open_probe_failure_makes_can_attempt_false_again(cb_clock):
    """After a failed probe re-opens at the advanced clock, can_attempt is immediately False."""
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)

    cb_clock.now += 30.0
    with pytest.raises(ValueError):
        _run(cb.call(_boom))

    assert cb._opened_at == cb_clock.now
    assert cb.can_attempt() is False


def test_can_attempt_false_before_recovery_timeout(cb_clock):
    """While OPEN and elapsed < recovery_timeout, can_attempt stays False."""
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)

    cb_clock.now += 29.999
    assert cb.can_attempt() is False


def test_can_attempt_true_exactly_at_recovery_timeout_boundary(cb_clock):
    """At elapsed == recovery_timeout the >= comparison flips can_attempt True."""
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)

    cb_clock.now += 30.0
    assert cb.can_attempt() is True


def test_can_attempt_true_when_closed(cb_clock):
    """A CLOSED breaker always permits attempts regardless of clock."""
    cb = CircuitBreaker("h", failure_threshold=2, recovery_timeout=30.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_attempt() is True


def test_can_attempt_true_when_half_open(cb_clock):
    """A HALF_OPEN breaker permits attempts regardless of elapsed cooldown."""
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    cb._state = CircuitState.HALF_OPEN
    assert cb.can_attempt() is True


def test_threshold_boundary_stays_closed_then_opens(cb_clock):
    """With threshold=3, the first two failures stay CLOSED, the third opens at the fake clock."""
    cb = CircuitBreaker("h", failure_threshold=3, recovery_timeout=30.0)

    _trip_open(cb, 1)
    assert cb.state == CircuitState.CLOSED
    assert cb.state != CircuitState.OPEN

    _trip_open(cb, 1)
    assert cb.state == CircuitState.CLOSED
    assert cb.state != CircuitState.OPEN

    cb_clock.now = 5000.0
    _trip_open(cb, 1)
    assert cb.state == CircuitState.OPEN
    assert cb._opened_at == 5000.0


def test_reset_clears_open_state(cb_clock):
    """reset() returns an OPEN breaker to CLOSED with zero failures and immediate availability."""
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)
    assert cb.state == CircuitState.OPEN

    cb.reset()

    assert cb.state == CircuitState.CLOSED
    assert cb._failures == 0
    assert cb.can_attempt() is True


def test_get_breaker_is_memoized(cb_clock):
    """Two calls for the same host return the identical breaker instance."""
    first = hb.get_breaker("a.com")
    second = hb.get_breaker("a.com")
    assert first is second


def test_get_breaker_uses_host_as_name(cb_clock):
    """The created breaker carries the host as its name."""
    breaker = hb.get_breaker("a.com")
    assert breaker.name == "a.com"


def test_get_breaker_empty_host_named_unknown(cb_clock):
    """An empty host yields a breaker named 'unknown'."""
    breaker = hb.get_breaker("")
    assert breaker.name == "unknown"


def test_host_disponible_empty_returns_true_without_entry(cb_clock):
    """An empty host is always available and creates no breaker entry."""
    assert hb.host_disponible("") is True
    assert "" not in hb._breakers


def test_host_disponible_question_mark_returns_true_without_entry(cb_clock):
    """The '?' sentinel host is always available and creates no breaker entry."""
    assert hb.host_disponible("?") is True
    assert "?" not in hb._breakers


def test_host_disponible_unknown_returns_true_without_entry(cb_clock):
    """An unknown host is available and is not lazily registered by the check."""
    assert hb.host_disponible("never-seen.tld") is True
    assert "never-seen.tld" not in hb._breakers


def test_host_disponible_isolation_open_host_blocked_other_ok(cb_clock):
    """A host tripped OPEN is unavailable while an untouched host stays available."""
    breaker = hb.get_breaker("A")
    breaker._threshold = 1
    with pytest.raises(ValueError):
        _run(breaker.call(_boom))

    assert hb.host_disponible("A") is False
    assert hb.host_disponible("B") is True


def test_breaker_shared_across_cdn_mirrors(cb_clock):
    """Les miroirs CDN d'un meme hote (registre) partagent un seul disjoncteur :
    un hote systematiquement casse declenche son breaker malgre des hostnames varies."""
    b1 = hb.get_breaker("d000d.com")
    b2 = hb.get_breaker("dood.watch")
    assert b1 is b2
    assert b1.name == "doodstream"

    b1._threshold = 1
    with pytest.raises(ValueError):
        _run(b1.call(_boom))

    assert hb.host_disponible("dood.watch") is False
    assert hb.host_disponible("d0o0d.com") is False
    assert hb.host_disponible("video.sibnet.ru") is True


def test_breaker_unknown_host_keeps_bare_key(cb_clock):
    """Un hote hors registre garde sa cle brute (pas de regroupement)."""
    b = hb.get_breaker("weird.unknown.tld")
    assert b.name == "weird.unknown.tld"
    assert hb.host_disponible("other.unknown.tld") is True


def test_reset_all_and_etat_breakers(cb_clock):
    """etat_breakers reports tripped hosts as open."""
    for host in ("A", "B"):
        breaker = hb.get_breaker(host)
        breaker._threshold = 1
        with pytest.raises(ValueError):
            _run(breaker.call(_boom))

    etat = hb.etat_breakers()
    assert etat["A"] == "open"
    assert etat["B"] == "open"


@pytest.fixture
def rl_clock(monkeypatch):
    """Fix _rate_limiter.time.time to a non-advancing fake clock."""
    state = {"now": 100000.0}
    monkeypatch.setattr(rl.time, "time", lambda: state["now"])
    return state


@pytest.fixture
def sleep_spy(monkeypatch):
    """Replace _rate_limiter.asyncio.sleep with an async recorder; never really sleeps."""
    recorded = []

    async def _fake_sleep(duration):
        recorded.append(duration)

    monkeypatch.setattr(rl.asyncio, "sleep", _fake_sleep)
    return recorded


def test_domain_wait_first_call_does_not_sleep(rl_clock, sleep_spy):
    """The first wait on a cleared cache reserves a slot but issues no sleep."""
    _run(rl.domain_wait("x.tld"))
    assert sleep_spy == []
    assert "x.tld" in rl._domain_last_access


def test_domain_wait_second_immediate_call_sleeps_min_delay(rl_clock, sleep_spy):
    """A second wait at the same instant sleeps for about the domain's min delay."""
    _run(rl.domain_wait("x.tld"))
    _run(rl.domain_wait("x.tld"))

    assert len(sleep_spy) == 1
    assert sleep_spy[0] == pytest.approx(rl.domain_min_delay("x.tld"), abs=0.05)


def test_domain_wait_empty_domain_is_noop(rl_clock, sleep_spy):
    """An empty domain neither sleeps nor records any cache entry."""
    before = set(rl._domain_last_access.keys())
    _run(rl.domain_wait(""))
    after = set(rl._domain_last_access.keys())

    assert sleep_spy == []
    assert before == after


def test_apply_penalty_then_wait_blocks_for_penalty_duration(rl_clock, sleep_spy):
    """After a penalty, an immediate wait sleeps for roughly the penalty duration."""
    domain = "sendvid.com"
    rl.domain_apply_penalty(domain)
    _run(rl.domain_wait(domain))

    assert len(sleep_spy) == 1
    assert sleep_spy[0] == pytest.approx(rl.domain_penalty(domain), abs=0.05)


def test_mark_used_does_not_move_future_slot_backward(rl_clock):
    """domain_mark_used keeps an existing future slot via max(prev, now)."""
    domain = "future.tld"
    future = rl_clock["now"] + 100.0
    rl._domain_last_access[domain] = future

    rl.domain_mark_used(domain)

    assert rl._domain_last_access[domain] == future


def test_purge_removes_only_expired_entries(rl_clock):
    """The purge drops entries older than the TTL and retains fresh ones."""
    now = rl_clock["now"]
    rl._domain_last_access["old"] = now - rl._DOMAIN_CACHE_TTL - 1
    rl._domain_last_access["fresh"] = now

    rl._purger_cache_verrou_tenu()

    assert "old" not in rl._domain_last_access
    assert "fresh" in rl._domain_last_access


def test_strategie_lecteur_subdomain_suffix_match():
    """A CDN subdomain of a known YTDLP domain resolves via the endswith branch."""
    assert strategie_lecteur({"src": "https://cdn.sendvid.com/v"}) == "ytdlp_first"


def test_strategie_lecteur_unknown_host_is_playwright_first():
    """A host that merely contains a known domain as a substring is not matched."""
    assert strategie_lecteur({"src": "https://notsendvid.com/v"}) == "playwright_first"


def test_strategie_lecteur_missing_src_defaults_without_raising():
    """A dict without 'src' falls back to playwright_first instead of raising."""
    assert strategie_lecteur({}) == "playwright_first"


def test_lecteur_url_valide_rejects_nonstring_src():
    """A non-string src short-circuits to invalid."""
    assert lecteur_url_valide({"src": 123}) is False


def test_lecteur_url_valide_rejects_nonhttp_scheme():
    """A non-http(s) scheme is rejected."""
    assert lecteur_url_valide({"src": "ftp://h/x"}) is False


def test_lecteur_url_valide_accepts_https():
    """A well-formed https src is accepted."""
    assert lecteur_url_valide({"src": "https://h.com/x"}) is True


def test_lecteur_url_valide_rejects_missing_key():
    """A dict without an src key is invalid."""
    assert lecteur_url_valide({}) is False

def test_call_while_open_within_cooldown_raises_runtimeerror(cb_clock):
    """While OPEN and before recovery_timeout, call() refuses without invoking func."""
    cb = CircuitBreaker("h", failure_threshold=2, recovery_timeout=30.0)
    _trip_open(cb, 2)
    assert cb.state == CircuitState.OPEN

    cb_clock.now += 10.0
    invoked = {"called": False}

    async def fn():
        invoked["called"] = True
        return "ok"

    with pytest.raises(RuntimeError):
        _run(cb.call(fn))
    assert invoked["called"] is False
    assert cb.state == CircuitState.OPEN
