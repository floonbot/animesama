"""Regression: on the final retry attempt, a persistent 429 must NOT sleep —
no further request follows, so the wait is wasted (up to 120s of dead time).
"""



import engine.scraping.http_client as hc


class _Resp:
    def __init__(self, status_code, ok, headers=None):
        self.status_code = status_code
        self.ok = ok
        self.headers = dict(headers or {})

    def close(self):
        pass


class _AsyncResp:
    def __init__(self, status_code, is_success, headers=None):
        self.status_code = status_code
        self.is_success = is_success
        self.headers = dict(headers or {})

    async def aclose(self):
        pass


class _Session:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append(url)
        return self._scripted.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(url)
        return self._scripted.pop(0)


def test_http_get_persistent_429_does_not_sleep_on_last_attempt(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hc.time, "sleep", lambda s: sleeps.append(s))
    throttled = [_Resp(429, False, {"Retry-After": "5"}) for _ in range(hc.HTTP_RETRIES + 1)]
    session = _Session(throttled)

    out = hc._http_get(session, "https://anime-sama.to/x")

    assert out is None
    assert len(session.calls) == hc.HTTP_RETRIES + 1
    assert len(sleeps) == hc.HTTP_RETRIES
    assert sleeps == [5.0] * hc.HTTP_RETRIES
