import asyncio

import pytest

from engine.utils import circuit_breaker as cbmod
from engine.utils.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


class _FakeMonotonic:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


@pytest.fixture
def cb_clock(monkeypatch):
    clock = _FakeMonotonic()
    monkeypatch.setattr(cbmod.time, "monotonic", clock)
    return clock


async def _boom():
    raise ValueError("boom")


def _run(coro):
    return asyncio.run(coro)


def _trip_open(cb, n):
    for _ in range(n):
        with pytest.raises(ValueError):
            _run(cb.call(_boom))


def test_open_within_cooldown_raises_circuit_open_error(cb_clock):
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)
    cb_clock.now += 10.0

    with pytest.raises(CircuitOpenError):
        _run(cb.call(_boom))


def test_circuit_open_error_is_runtimeerror():
    assert issubclass(CircuitOpenError, RuntimeError)


def test_half_open_allows_only_one_concurrent_probe(cb_clock):
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)
    cb_clock.now += 30.0

    gate = asyncio.Event()
    probe_calls = {"n": 0}

    async def slow_probe():
        probe_calls["n"] += 1
        await gate.wait()
        return "ok"

    async def scenario():
        first = asyncio.ensure_future(cb.call(slow_probe))
        await asyncio.sleep(0)
        assert cb.state == CircuitState.HALF_OPEN
        with pytest.raises(CircuitOpenError):
            await cb.call(slow_probe)
        gate.set()
        return await first

    assert _run(scenario()) == "ok"
    assert probe_calls["n"] == 1


def test_probe_flag_cleared_on_failure_allows_next_probe(cb_clock):
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)
    cb_clock.now += 30.0

    with pytest.raises(ValueError):
        _run(cb.call(_boom))
    assert cb.state == CircuitState.OPEN

    cb_clock.now += 60.0

    async def ok():
        return "ok"

    assert _run(cb.call(ok)) == "ok"
    assert cb.state == CircuitState.CLOSED


def test_recovery_backoff_doubles_after_reopen(cb_clock):
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)
    cb_clock.now += 30.0

    with pytest.raises(ValueError):
        _run(cb.call(_boom))
    assert cb.state == CircuitState.OPEN

    cb_clock.now += 30.0
    assert cb.can_attempt() is False

    cb_clock.now += 30.0
    assert cb.can_attempt() is True


def test_recovery_backoff_resets_after_success(cb_clock):
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)
    _trip_open(cb, 1)
    cb_clock.now += 30.0
    with pytest.raises(ValueError):
        _run(cb.call(_boom))

    async def ok():
        return "ok"

    cb_clock.now += 60.0
    assert _run(cb.call(ok)) == "ok"
    assert cb.state == CircuitState.CLOSED

    _trip_open(cb, 1)
    cb_clock.now += 30.0
    assert cb.can_attempt() is True


def test_recovery_backoff_capped(cb_clock):
    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0, max_recovery_timeout=60.0)
    _trip_open(cb, 1)
    for _ in range(5):
        cb_clock.now += 60.0
        with pytest.raises(ValueError):
            _run(cb.call(_boom))
    cb_clock.now += 60.0
    assert cb.can_attempt() is True
