import inspect
import threading

from engine.download.methods._ffmpeg_parsing import ProgressState
from engine.download.methods.ffmpeg_engine import _lire_stdout_ffmpeg


def test_lire_stdout_ffmpeg_draine_et_parse_sans_accumuler():
    lignes = [
        "out_time=00:00:50",
        "total_size=1048576",
        "speed= 2.0x",
        "bitrate= 128.0kbits/s",
        "",
        "progress=continue",
        "progress=end",
    ]
    state = ProgressState()
    ready = threading.Event()

    _lire_stdout_ffmpeg(iter(lignes), state, ready)

    assert state.out_time_s == 50.0
    assert state.total_size == 1048576
    assert state.speed == 2.0
    assert state.bitrate == 128.0
    assert state.done is True
    assert ready.is_set()


def test_lire_stdout_ffmpeg_ferme_toujours_le_ready_sur_erreur():
    class _PipeExplosif:
        def __iter__(self):
            return self

        def __next__(self):
            raise RuntimeError("pipe cassé")

    state = ProgressState()
    ready = threading.Event()

    _lire_stdout_ffmpeg(_PipeExplosif(), state, ready)

    assert ready.is_set()


def test_lire_stdout_ffmpeg_ne_conserve_plus_les_lignes():
    params = list(inspect.signature(_lire_stdout_ffmpeg).parameters)
    assert params == ["pipe", "state", "stdout_ready"]
