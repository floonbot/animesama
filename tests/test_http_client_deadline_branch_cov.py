import requests as req

import engine.scraping.http_client as hc


class _TimeoutSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        raise req.exceptions.Timeout("slow server")


def test_http_get_aborts_when_total_deadline_exceeded(monkeypatch):
    clock = {"vals": [0.0, 0.0, 9999.0]}

    def _mono():
        v = clock["vals"]
        return v.pop(0) if len(v) > 1 else v[0]

    monkeypatch.setattr(hc.time, "monotonic", _mono)
    monkeypatch.setattr(hc.time, "sleep", lambda d: None)

    session = _TimeoutSession()
    result = hc._http_get(session, "https://x/y")

    assert result is None
    assert session.calls < hc.HTTP_RETRIES + 1
