"""Regression (blocage) : _fermer_page_ctx libérait le sémaphore de contextes
*après* page.close() / ctx.close(). Ces await s'exécutent dans un finally pendant
l'annulation ; une CancelledError qui y remonte n'est pas attrapée par
`except Exception`, et le permit n'était jamais rendu.

Quatre annulations pendant une interception suffisaient alors à épuiser les
MAX_CONTEXTS_SIMULTANES permis : toute interception Playwright ultérieure
attendait indéfiniment, jusqu'au redémarrage de l'app.
"""

import asyncio

import pytest

from engine.download import interceptor


class _Fermeture:
    def __init__(self, exc=None):
        self.appele = False
        self._exc = exc

    async def close(self):
        self.appele = True
        if self._exc is not None:
            raise self._exc


def test_le_permit_est_rendu_si_page_close_est_annule():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        page = _Fermeture(asyncio.CancelledError())
        ctx = _Fermeture()

        with pytest.raises(asyncio.CancelledError):
            await interceptor._fermer_page_ctx(page, ctx, sem, True, False, True)

        assert sem.locked() is False
        assert ctx.appele is True, "le contexte doit être fermé même si la page échoue"

    asyncio.run(scenario())


def test_le_permit_est_rendu_si_ctx_close_est_annule():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        ctx = _Fermeture(asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await interceptor._fermer_page_ctx(None, ctx, sem, True, False, True)

        assert sem.locked() is False

    asyncio.run(scenario())


def test_le_permit_est_rendu_en_fonctionnement_normal():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        page, ctx = _Fermeture(), _Fermeture()

        await interceptor._fermer_page_ctx(page, ctx, sem, True, False, True)

        assert sem.locked() is False
        assert page.appele and ctx.appele

    asyncio.run(scenario())


def test_pas_de_liberation_si_pas_acquis():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await interceptor._fermer_page_ctx(None, None, sem, False, False, True)
        assert sem._value == 1

    asyncio.run(scenario())


def test_quatre_annulations_ne_bloquent_pas_les_interceptions_suivantes():
    """Contre-épreuve : le sémaphore reste utilisable après MAX_CONTEXTS annulations."""
    async def scenario():
        sem = asyncio.Semaphore(interceptor.MAX_CONTEXTS_SIMULTANES)
        for _ in range(interceptor.MAX_CONTEXTS_SIMULTANES):
            await sem.acquire()
            with pytest.raises(asyncio.CancelledError):
                await interceptor._fermer_page_ctx(
                    _Fermeture(asyncio.CancelledError()), None, sem, True, False, True
                )
        await asyncio.wait_for(sem.acquire(), timeout=1.0)

    asyncio.run(scenario())
