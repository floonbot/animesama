
import logging
import time
from enum import Enum

log = logging.getLogger("engine.utils.circuit_breaker")

class CircuitState(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"

class CircuitOpenError(RuntimeError):
    pass

class CircuitBreaker:

    def __init__(
        self,
        name:                 str,
        failure_threshold:    int   = 5,
        recovery_timeout:     float = 60.0,
        max_recovery_timeout: float | None = None,
    ):
        self.name               = name
        self._threshold         = failure_threshold
        self._recovery_timeout  = recovery_timeout
        self._max_recovery      = max_recovery_timeout if max_recovery_timeout is not None else recovery_timeout * 8
        self._failures          = 0
        self._open_streak       = 0
        self._state             = CircuitState.CLOSED
        self._opened_at:  float = 0.0
        self._probing           = False

    def _effective_recovery(self) -> float:
        exp = max(0, self._open_streak - 1)
        return min(self._recovery_timeout * (2 ** exp), self._max_recovery)

    @property
    def state(self) -> CircuitState:
        return self._state

    def can_attempt(self) -> bool:
        if self._state != CircuitState.OPEN:
            return True
        return (time.monotonic() - self._opened_at) >= self._effective_recovery()

    async def call(self, func, *args, **kwargs):
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self._effective_recovery():
                self._state = CircuitState.HALF_OPEN
                self._probing = True
                log.info(f"[CircuitBreaker:{self.name}] → HALF_OPEN (test récupération)")
            else:
                remaining = self._effective_recovery() - elapsed
                raise CircuitOpenError(
                    f"Circuit OUVERT pour '{self.name}'. "
                    f"Réessai dans {remaining:.0f}s"
                )
        elif self._state == CircuitState.HALF_OPEN and self._probing:
            raise CircuitOpenError(f"Circuit en test pour '{self.name}'")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise
        except BaseException:
            self._probing = False
            raise

    def _on_success(self) -> None:
        if self._state != CircuitState.CLOSED:
            log.info(f"[CircuitBreaker:{self.name}] → CLOSED (récupéré)")
        self._failures = 0
        self._open_streak = 0
        self._state    = CircuitState.CLOSED
        self._probing  = False

    def _on_failure(self, exc: Exception) -> None:
        self._failures += 1
        self._probing = False
        if self._failures >= self._threshold:
            self._open_streak += 1
            self._state     = CircuitState.OPEN
            self._opened_at = time.monotonic()
            log.error(
                f"[CircuitBreaker:{self.name}] → OPEN après {self._failures} échecs "
                f"(dernier : {type(exc).__name__}: {exc})"
            )
        else:
            log.warning(
                f"[CircuitBreaker:{self.name}] échec {self._failures}/{self._threshold} "
                f"({type(exc).__name__})"
            )

    def reset(self) -> None:
        self._failures   = 0
        self._open_streak = 0
        self._state      = CircuitState.CLOSED
        self._opened_at  = 0.0
        self._probing    = False

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(name={self.name!r}, state={self._state.value}, "
            f"failures={self._failures}/{self._threshold})"
        )
