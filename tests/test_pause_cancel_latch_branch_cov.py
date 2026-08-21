import pytest

from engine.download.methods import _proc_registry as pr
from engine.download.queue import DownloadQueue
from engine.download.store import DownloadStore


@pytest.fixture
def store(tmp_path):
    s = DownloadStore(tmp_path / "d.db")
    yield s
    s.close()


def test_annuler_reinitialise_le_latch_de_pause(store):
    q = DownloadQueue()
    q._store = store
    q._current = {"i": -1}

    assert q.pause() is True
    assert pr._pause_en_cours is True

    assert q.annuler() is True
    assert pr._pause_en_cours is False


def test_shutdown_preserve_reinitialise_le_latch_de_pause(store):
    q = DownloadQueue()
    q._store = store
    q._current = {"i": -1}

    assert q.pause() is True
    assert pr._pause_en_cours is True

    assert q.shutdown_preserve() is True
    assert pr._pause_en_cours is False
