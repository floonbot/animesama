import asyncio
import threading

import pytest

import engine.config.settings as settings
from engine.services.download_service import DownloadService


class FakeQueue:
    def __init__(self):
        self.ajoutes: list = []

    async def ajouter(self, item):
        self.ajoutes.append(item)
        return len(self.ajoutes)

    def statut(self):
        return {}


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    s = DownloadService()
    s._queue = FakeQueue()
    return s


def test_ajouter_direct_validates_off_the_event_loop_thread(svc, monkeypatch):
    seen: dict = {}

    def fake_validate(u):
        seen["tid"] = threading.get_ident()
        return u

    monkeypatch.setattr(
        "engine.services.download_service.validate_external_url", fake_validate
    )

    async def scenario():
        loop_tid = threading.get_ident()
        out = await svc.ajouter_direct("https://host/s.m3u8", "N")
        assert out["ok"] is True
        return loop_tid

    loop_tid = asyncio.run(scenario())
    assert seen["tid"] != loop_tid
