import asyncio

from engine.download import _rate_limiter as rl


def _reset():
    rl._recent_bans.clear()
    rl._domain_last_access.clear()
    rl._domain_penalty_active.clear()


def test_cooldown_global_zero_below_seuil():
    _reset()
    try:
        assert rl.cooldown_global() == 0.0
        rl.domain_apply_penalty("a.tld")
        rl.domain_apply_penalty("b.tld")
        assert rl.bans_recents() == 2
        assert rl.cooldown_global() == 0.0
    finally:
        _reset()


def test_cooldown_global_escalates_and_caps():
    _reset()
    try:
        for i in range(rl._BAN_COOLDOWN_SEUIL):
            rl.domain_apply_penalty(f"h{i}.tld")
        assert rl.cooldown_global() == rl._BAN_COOLDOWN_PAS
        for i in range(rl._BAN_COOLDOWN_SEUIL, 40):
            rl.domain_apply_penalty(f"h{i}.tld")
        assert rl.cooldown_global() == rl._BAN_COOLDOWN_MAX
    finally:
        _reset()


def test_elaguer_bans_prunes_old_window():
    _reset()
    try:
        rl._recent_bans.append(1.0)
        rl.domain_apply_penalty("x.tld")
        assert 1.0 not in rl._recent_bans
        assert rl.bans_recents() == 1
    finally:
        _reset()


def test_pause_anti_ban_fast_path_no_cooldown(monkeypatch):
    from engine.download import worker

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr("engine.download._rate_limiter.cooldown_global", lambda: 0.0)

    asyncio.run(worker._pause_anti_ban(object()))
    assert slept == [worker.DELAI_MIN_EPISODES]


def test_pause_anti_ban_emits_and_sleeps_when_throttled(monkeypatch):
    from engine.download import worker

    slept = []
    emits = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr("engine.download._rate_limiter.cooldown_global", lambda: 6.0)
    monkeypatch.setattr(worker, "_safe_emit", lambda q, ev, data: emits.append(ev))
    monkeypatch.setattr(worker, "_est_annule", lambda q: False)

    asyncio.run(worker._pause_anti_ban(object()))
    assert "episode_progress" in emits
    assert sum(slept) >= worker.DELAI_MIN_EPISODES + 6.0 - 1.0
