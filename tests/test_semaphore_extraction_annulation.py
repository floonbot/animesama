"""Regression (blocage) : meme defaut que dans `interceptor._fermer_page_ctx`,
mais dans `browser_extractor._fermer_ressources` — qui partage le *meme*
semaphore (`interceptor._ctx_semaphore`).

`cdp.detach()` / `page.close()` / `ctx.close()` sont attendus dans un finally,
donc potentiellement pendant une annulation. Une CancelledError qui y remonte
n'est pas rattrapee par `except Exception` et emporte le `sem.release()` final.

L'extraction forensic est le dernier recours de la cascade : quatre annulations
pendant cette etape epuisaient MAX_CONTEXTS_SIMULTANES et bloquaient ensuite
*toutes* les interceptions Playwright, jusqu'au redemarrage.
"""

import asyncio

import pytest

from engine.download import interceptor
from engine.download.extractor import browser_extractor as bx


class _Fermeture:
    def __init__(self, exc=None):
        self.appele = False
        self._exc = exc

    async def close(self):
        self.appele = True
        if self._exc is not None:
            raise self._exc


class _Cdp:
    def __init__(self, exc=None):
        self.appele = False
        self._exc = exc

    async def detach(self):
        self.appele = True
        if self._exc is not None:
            raise self._exc


def test_le_permit_est_rendu_si_cdp_detach_est_annule():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        cdp = _Cdp(asyncio.CancelledError())
        page, ctx = _Fermeture(), _Fermeture()

        with pytest.raises(asyncio.CancelledError):
            await bx._fermer_ressources(cdp, page, ctx, sem, True, False)

        assert sem.locked() is False
        assert page.appele and ctx.appele, "page et contexte doivent etre fermes quand meme"

    asyncio.run(scenario())


def test_le_permit_est_rendu_si_page_close_est_annule():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        page = _Fermeture(asyncio.CancelledError())
        ctx = _Fermeture()

        with pytest.raises(asyncio.CancelledError):
            await bx._fermer_ressources(None, page, ctx, sem, True, False)

        assert sem.locked() is False
        assert ctx.appele is True

    asyncio.run(scenario())


def test_le_permit_est_rendu_si_ctx_close_est_annule():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        ctx = _Fermeture(asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await bx._fermer_ressources(None, None, ctx, sem, True, False)

        assert sem.locked() is False

    asyncio.run(scenario())


def test_le_permit_est_rendu_en_fonctionnement_normal():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        cdp, page, ctx = _Cdp(), _Fermeture(), _Fermeture()

        await bx._fermer_ressources(cdp, page, ctx, sem, True, False)

        assert sem.locked() is False
        assert cdp.appele and page.appele and ctx.appele

    asyncio.run(scenario())


def test_une_erreur_ordinaire_reste_avalee():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        page = _Fermeture(RuntimeError("target closed"))
        ctx = _Fermeture()

        await bx._fermer_ressources(None, page, ctx, sem, True, False)

        assert sem.locked() is False
        assert ctx.appele is True

    asyncio.run(scenario())


def test_pas_de_liberation_si_pas_acquis():
    async def scenario():
        sem = asyncio.Semaphore(1)
        await bx._fermer_ressources(None, None, None, sem, False, False)
        assert sem._value == 1

    asyncio.run(scenario())


def test_quatre_annulations_ne_bloquent_pas_les_extractions_suivantes():
    """Contre-epreuve : le semaphore partage reste utilisable apres MAX_CONTEXTS annulations."""

    async def scenario():
        sem = asyncio.Semaphore(interceptor.MAX_CONTEXTS_SIMULTANES)
        for _ in range(interceptor.MAX_CONTEXTS_SIMULTANES):
            await sem.acquire()
            with pytest.raises(asyncio.CancelledError):
                await bx._fermer_ressources(
                    None, _Fermeture(asyncio.CancelledError()), None, sem, True, False
                )
        await asyncio.wait_for(sem.acquire(), timeout=1.0)

    asyncio.run(scenario())
