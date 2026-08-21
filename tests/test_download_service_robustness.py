import asyncio

from engine.services.download_service import DownloadService
from engine.utils.security import sanitize_filename


class _FakeQueue:
    def __init__(self):
        self.items = []

    async def ajouter(self, item):
        self.items.append(item)
        return len(self.items)

    def statut(self):
        return {}


def _svc():
    svc = DownloadService()
    svc._queue = _FakeQueue()
    return svc


def test_ajouter_episode_ok_when_saison_not_int():
    svc = _svc()
    item = {
        "ep": {"titre": "X", "saison": "abc", "episode": 5},
        "episodes": [{"titre": "X", "saison": "abc", "episode": 5}],
    }
    out = asyncio.run(svc.ajouter_episode(item))
    assert out["ok"] is True
    assert len(svc._queue.items) == 1


def test_ajouter_episode_sanitizes_batch_titles():
    svc = _svc()
    item = {
        "ep": {"titre": "Clean", "saison": 1, "episode": 1},
        "episodes": [
            {"titre": "Bad\x00Name", "saison": 1, "episode": 1},
            {"titre": "Ok/Other", "saison": 1, "episode": 2},
        ],
    }
    asyncio.run(svc.ajouter_episode(item))
    eps = svc._queue.items[0]["episodes"]
    assert eps[0]["titre"] == sanitize_filename("Bad\x00Name")
    assert eps[1]["titre"] == sanitize_filename("Ok/Other")
    assert "\x00" not in eps[0]["titre"]
