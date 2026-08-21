import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine.domain.exceptions import AnimeDownloaderError, DownloadCancelled


def test_download_cancelled_is_runtime_error():
    exc = DownloadCancelled()
    assert isinstance(exc, RuntimeError)
    assert isinstance(exc, AnimeDownloaderError)

def test_download_cancelled_default_message():
    assert "Annulé" in str(DownloadCancelled())

def test_caught_as_runtime_error():
    caught = False
    try:
        raise DownloadCancelled()
    except RuntimeError:
        caught = True
    assert caught
