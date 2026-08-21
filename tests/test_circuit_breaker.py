import asyncio

from engine.utils.circuit_breaker import CircuitBreaker, CircuitState


def _run(coro):
    return asyncio.run(coro)

def test_opens_after_threshold():
    cb = CircuitBreaker("t", failure_threshold=2, recovery_timeout=60.0)

    async def boom():
        raise ValueError("x")

    for _ in range(2):
        try:
            _run(cb.call(boom))
        except ValueError:
            pass
    assert cb.state == CircuitState.OPEN

def test_blocks_calls_when_open():
    cb = CircuitBreaker("t", failure_threshold=1, recovery_timeout=60.0)

    async def boom():
        raise ValueError("x")

    try:
        _run(cb.call(boom))
    except ValueError:
        pass

    async def ok():
        return 42

    try:
        _run(cb.call(ok))
        assert False, "should have raised"
    except RuntimeError:
        pass

def test_success_resets():
    cb = CircuitBreaker("t", failure_threshold=3)

    async def ok():
        return 1

    assert _run(cb.call(ok)) == 1
    assert cb.state == CircuitState.CLOSED
