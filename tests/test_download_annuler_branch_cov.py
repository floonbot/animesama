import asyncio
import threading

from engine.services.download_service import download_service
from web.api.routes import download as dl_route


def test_annuler_runs_off_event_loop(monkeypatch):
    rec: dict[str, int] = {}

    def fake_annuler():
        rec["thread"] = threading.get_ident()
        return {"ok": True, "statut": {}}

    monkeypatch.setattr(download_service, "annuler", fake_annuler)

    async def run():
        rec["loop"] = threading.get_ident()
        return await dl_route.annuler()

    result = asyncio.run(run())
    assert result == {"ok": True, "statut": {}}
    assert rec["thread"] != rec["loop"]


def test_annuler_exception_degrades(monkeypatch):
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(download_service, "annuler", boom)
    assert asyncio.run(dl_route.annuler()) == {"ok": False}
