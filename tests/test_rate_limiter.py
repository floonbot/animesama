from engine.download import _rate_limiter as rl


def test_known_domain_has_specific_delay():
    assert rl.domain_min_delay("video.sibnet.ru") >= 5.0

def test_unknown_domain_uses_default():
    assert rl.domain_min_delay("totally-unknown.tld") == rl.DOMAIN_MIN_DELAY_DEFAULT

def test_penalty_pushes_last_access_into_future():
    rl._domain_last_access.pop("sendvid.com", None)
    rl.domain_apply_penalty("sendvid.com")
    assert "sendvid.com" in rl._domain_last_access

def test_mark_used_records_timestamp():
    rl._domain_last_access.pop("example.tld", None)
    rl.domain_mark_used("example.tld")
    assert rl._domain_last_access.get("example.tld", 0) > 0

def test_penalty_escalates_on_repeated_bans():
    d = "escalate.example"
    rl._domain_last_access.pop(d, None)
    rl._domain_penalty_active.pop(d, None)
    try:
        base = rl.domain_penalty(d)
        rl.domain_apply_penalty(d)
        p1 = rl._domain_penalty_active[d]
        rl.domain_apply_penalty(d)
        p2 = rl._domain_penalty_active[d]
        assert p1 == base
        assert p2 > p1
        assert p2 <= base * rl._BAN_ESCALATION_CAP
    finally:
        rl._domain_last_access.pop(d, None)
        rl._domain_penalty_active.pop(d, None)

def test_penalty_first_ban_equals_base():
    d = "freshban.example"
    rl._domain_last_access.pop(d, None)
    rl._domain_penalty_active.pop(d, None)
    try:
        rl.domain_apply_penalty(d)
        assert rl._domain_penalty_active[d] == rl.domain_penalty(d)
    finally:
        rl._domain_last_access.pop(d, None)
        rl._domain_penalty_active.pop(d, None)
