"""Regression: a CircuitBreaker probe cancelled mid-flight must not leave the
breaker stuck in HALF_OPEN with _probing=True forever. asyncio.CancelledError is
a BaseException, so the old `except Exception` never cleared _probing; every
later call then raised CircuitOpenError permanently. The fix clears _probing on
any BaseException (while still re-raising), so the next call re-probes.

Order-safe: time.monotonic is monkeypatched per-test; no global mutation leaks.
"""

import asyncio

import pytest

import engine.utils.circuit_breaker as cbmod
from engine.utils.circuit_breaker import CircuitBreaker, CircuitState


class _Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


def test_probe_cancelled_does_not_wedge_half_open(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(cbmod.time, "monotonic", clock)

    cb = CircuitBreaker("h", failure_threshold=1, recovery_timeout=30.0)

    async def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        asyncio.run(cb.call(boom))
    assert cb.state == CircuitState.OPEN

    clock.now += 30.0

    async def scenario():
        async def hang():
            await asyncio.Event().wait()

        task = asyncio.ensure_future(cb.call(hang))
        await asyncio.sleep(0)
        assert cb.state == CircuitState.HALF_OPEN
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert cb._probing is False

    async def ok():
        return "ok"

    assert asyncio.run(cb.call(ok)) == "ok"
    assert cb.state == CircuitState.CLOSED
