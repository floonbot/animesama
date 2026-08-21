import asyncio

import pytest

from engine.download import _rate_limiter as rl


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    snap = dict(rl._domain_last_access)
    snap_pen = dict(rl._domain_penalty_active)
    rl._domain_last_access.clear()
    rl._domain_penalty_active.clear()
    yield
    rl._domain_last_access.clear()
    rl._domain_last_access.update(snap)
    rl._domain_penalty_active.clear()
    rl._domain_penalty_active.update(snap_pen)


def test_domain_wait_is_capped_on_backward_clock_jump(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(rl.time, "time", lambda: clock["t"])

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(rl.asyncio, "sleep", fake_sleep)

    domain = "evil.example"
    rl.domain_apply_penalty(domain)

    clock["t"] = 1000.0 - 3600.0

    asyncio.run(rl.domain_wait(domain))

    assert slept, "domain_wait should have slept"
    cap = max(rl.domain_min_delay(domain), rl.domain_penalty(domain))
    assert slept[-1] <= cap + 0.01, f"wait {slept[-1]} not capped to {cap}"


def test_domain_wait_normal_path_unchanged(monkeypatch):
    clock = {"t": 5000.0}
    monkeypatch.setattr(rl.time, "time", lambda: clock["t"])

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(rl.asyncio, "sleep", fake_sleep)

    domain = "sibnet.example"
    rl.domain_mark_used(domain)
    asyncio.run(rl.domain_wait(domain))

    if slept:
        assert slept[-1] <= rl.domain_min_delay(domain) + 0.01


def test_penalty_does_not_shorten_future_reservation(monkeypatch):
    clock = {"t": 100000.0}
    monkeypatch.setattr(rl.time, "time", lambda: clock["t"])

    domain = "reserve.example"
    min_delay = rl.domain_min_delay(domain)
    far_future = clock["t"] + 1000.0
    rl._domain_last_access[domain] = far_future

    rl.domain_apply_penalty(domain)

    stored = rl._domain_last_access[domain]
    assert stored + min_delay >= far_future
    naive = clock["t"] + rl.domain_penalty(domain) - min_delay
    assert stored > naive
