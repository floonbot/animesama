"""Un disjoncteur par hebergeur video, indexe sur le nom canonique.

Les hebergeurs changent de domaine sans changer de service : vidmoly.to,
.net et .biz sont la meme machine derriere. _canon() les ramene au nom de
l'extracteur, sinon chaque nouveau domaine repartirait avec un compteur
d'echecs vierge et le disjoncteur ne se declencherait jamais.
"""

import logging
import threading

from engine.utils.circuit_breaker import CircuitBreaker

log = logging.getLogger("engine.download.host_breakers")

_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()

_FAILURE_THRESHOLD = 4
_RECOVERY_TIMEOUT  = 120.0

def _canon(host: str) -> str:
    try:
        from engine.download.extractor.registry import get_extractor
        ext = get_extractor(host)
        if ext.name != "generic":
            return ext.name
    except Exception:
        return host
    return host

def get_breaker(host: str) -> CircuitBreaker:
    host = _canon(host)
    with _breakers_lock:
        breaker = _breakers.get(host)
        if breaker is None:
            breaker = CircuitBreaker(
                name=host or "unknown",
                failure_threshold=_FAILURE_THRESHOLD,
                recovery_timeout=_RECOVERY_TIMEOUT,
            )
            _breakers[host] = breaker
    return breaker

def host_disponible(host: str) -> bool:
    if not host or host == "?":
        return True
    host = _canon(host)
    with _breakers_lock:
        breaker = _breakers.get(host)
    if breaker is None:
        return True
    return breaker.can_attempt()

def etat_breakers() -> dict[str, str]:
    with _breakers_lock:
        return {host: b.state.value for host, b in _breakers.items()}
