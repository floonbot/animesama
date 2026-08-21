"""Primitives asyncio liees a la boucle qui les a creees.

Un asyncio.Lock construit sur une boucle et attendu sur une autre leve
RuntimeError. Or ce processus en demarre plusieurs : uvicorn, les tests, et
chaque asyncio.run() ponctuel. Les objets construits ici sont donc recrees
quand la boucle courante change, plutot que memorises une fois pour toutes.
"""

import asyncio
import threading
from collections.abc import Callable


class LoopLocal[T]:

    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._obj: T | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mutex = threading.Lock()

    def get(self) -> T | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        if self._obj is not None and self._loop is loop:
            return self._obj
        with self._mutex:
            if self._obj is None or self._loop is not loop:
                self._obj = self._factory()
                self._loop = loop
        return self._obj

    def require(self) -> T:
        obj = self.get()
        if obj is None:
            raise RuntimeError("loop-local accessed without a running event loop")
        return obj

def loop_local_lock() -> "LoopLocal[asyncio.Lock]":
    return LoopLocal(asyncio.Lock)

def loop_local_semaphore(value: int) -> "LoopLocal[asyncio.Semaphore]":
    return LoopLocal(lambda: asyncio.Semaphore(value))
