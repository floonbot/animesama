"""_run_in_pool doit propager le contexte au thread du pool, sur ses deux branches.

Le pool est un ThreadPoolExecutor : sans le contextvars.copy_context() explicite,
la fonction executee y perd le task_id et ses lignes de journal repartent sans
identifiant, au milieu de celles des autres taches. Le branchement « moteur » vs
« non-moteur » suit deux chemins distincts, d'ou les deux cas.
"""

import asyncio

import pytest

from engine.download import _runtime as runtime
from engine.observability.context import get_task_id, reset_task_id, set_task_id
from engine.observability.metrics import metrics


@pytest.fixture
def reset_metrics():
    metrics.reset()
    yield
    metrics.reset()


def _named(name, fn):
    fn.__name__ = name
    return fn


def _tid_reader(seen):
    def body(*a):
        seen["tid"] = get_task_id()
        return "x"

    return body


def test_run_in_pool_propagates_task_id_on_non_engine_branch():
    seen: dict = {}

    async def go():
        token = set_task_id("abc123")
        try:
            return await runtime._run_in_pool(_named("some_helper", _tid_reader(seen)))
        finally:
            reset_task_id(token)

    out = asyncio.run(go())

    assert out == "x"
    assert seen["tid"] == "abc123"


def test_run_in_pool_propagates_task_id_on_engine_branch(reset_metrics):
    seen: dict = {}

    async def go():
        token = set_task_id("abc123")
        try:
            await runtime._run_in_pool(_named("ytdlp_download", _tid_reader(seen)))
        finally:
            reset_task_id(token)

    asyncio.run(go())

    assert seen["tid"] == "abc123"
    assert metrics.snapshot().get("download_ytdlp_attempts") == 1
