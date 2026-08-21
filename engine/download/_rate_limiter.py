"""Etalement des acces par domaine, pour ne pas se faire bannir.

Trois mecanismes distincts, souvent confondus :
- `domain_wait` reserve un creneau futur par domaine (delai minimum entre deux
  acces) ; le creneau est pose *avant* l'attente, donc deux coroutines qui
  demandent en meme temps s'etalent au lieu de partir ensemble ;
- `domain_apply_penalty` allonge ce delai apres un 403, en cumulant avec ce qui
  reste a attendre et en plafonnant a _BAN_ESCALATION_CAP fois la penalite ;
- `hote_throttle` met un hote entierement de cote (429, page de parking).
`cooldown_global` s'ajoute par-dessus : au-dela de trois bans en cinq minutes,
c'est le site entier qui nous surveille, pas un domaine.
"""

import asyncio
import logging
import threading
import time

from engine.config.settings import (
    DOMAIN_MIN_DELAY_DEFAULT,
    DOMAIN_MIN_DELAYS,
    DOMAIN_PENALTY_DELAY_DEFAULT,
    DOMAIN_PENALTY_DELAYS,
)

log = logging.getLogger("engine.download.rate_limiter")

_DOMAIN_CACHE_TTL = 86_400

_domain_last_access: dict[str, float] = {}
_domain_penalty_active: dict[str, float] = {}
_domain_lock = threading.Lock()

_BAN_ESCALATION_CAP = 6

_recent_bans: list[float] = []
_BAN_WINDOW_S = 300.0
_BAN_COOLDOWN_SEUIL = 3
_BAN_COOLDOWN_PAS = 30.0
_BAN_COOLDOWN_MAX = 120.0

_host_throttle: dict[str, float] = {}
HOST_THROTTLE_MAX = 200

def domain_min_delay(domain: str) -> float:
    return DOMAIN_MIN_DELAYS.get(domain, DOMAIN_MIN_DELAY_DEFAULT)

def domain_penalty(domain: str) -> float:
    return DOMAIN_PENALTY_DELAYS.get(domain, DOMAIN_PENALTY_DELAY_DEFAULT)

async def domain_wait(domain: str) -> None:
    if not domain:
        return
    min_delay = domain_min_delay(domain)
    with _domain_lock:
        now = time.time()
        last = _domain_last_access.get(domain, 0.0)
        slot = max(now, last + min_delay)
        _domain_last_access[domain] = slot
        if slot <= now + 0.1:
            _domain_penalty_active.pop(domain, None)
        eff = _domain_penalty_active.get(domain, domain_penalty(domain))
        if len(_domain_last_access) > 50:
            _purger_cache_verrou_tenu()
    wait = slot - time.time()
    if wait > 0.1:
        wait = min(wait, max(min_delay, eff))
        log.debug(f"Rate-limit guard [{domain}] : attente {wait:.1f}s")
        await asyncio.sleep(wait)

def domain_mark_used(domain: str) -> None:
    if not domain:
        return
    with _domain_lock:
        prev = _domain_last_access.get(domain, 0.0)
        _domain_last_access[domain] = max(prev, time.time())
        if len(_domain_last_access) > 50:
            _purger_cache_verrou_tenu()

def domain_apply_penalty(domain: str) -> None:
    if not domain:
        return
    base = domain_penalty(domain)
    min_delay = domain_min_delay(domain)
    now = time.time()
    with _domain_lock:
        current = _domain_last_access.get(domain, 0.0)
        reste = current + min_delay - now
        pen = base + reste if reste > 0.1 else base
        pen = min(pen, base * _BAN_ESCALATION_CAP)
        _domain_penalty_active[domain] = pen
        _domain_last_access[domain] = max(current, now + pen) - min_delay
        _recent_bans.append(now)
        _elaguer_bans(now)
    log.warning(
        f"Rate-limit 403 [{domain}] : pause {pen:.0f}s avant prochain accès"
    )

def _elaguer_bans(now: float) -> None:
    seuil = now - _BAN_WINDOW_S
    if _recent_bans and _recent_bans[0] < seuil:
        _recent_bans[:] = [ts for ts in _recent_bans if ts >= seuil]

def bans_recents(fenetre: float = _BAN_WINDOW_S) -> int:
    seuil = time.time() - fenetre
    with _domain_lock:
        return sum(1 for ts in _recent_bans if ts >= seuil)

def cooldown_global() -> float:
    n = bans_recents()
    if n < _BAN_COOLDOWN_SEUIL:
        return 0.0
    extra = (n - _BAN_COOLDOWN_SEUIL + 1) * _BAN_COOLDOWN_PAS
    return min(extra, _BAN_COOLDOWN_MAX)

def marquer_hote_throttle(domain: str) -> None:
    if not domain:
        return
    duree = domain_penalty(domain)
    with _domain_lock:
        _host_throttle[domain] = time.time() + duree
        _purger_throttle_verrou_tenu()
    log.debug(f"Hôte throttlé [{domain}] : ignoré pendant {duree:.0f}s (429/parking)")

def _purger_throttle_verrou_tenu() -> None:
    # hote_throttle() ne nettoie que l'hôte interroge : sans ce balayage, un
    # process qui tourne des heures accumule une entree par hôte croise.
    maintenant = time.time()
    for d in [d for d, until in _host_throttle.items() if until <= maintenant]:
        _host_throttle.pop(d, None)
    if len(_host_throttle) > HOST_THROTTLE_MAX:
        surplus = len(_host_throttle) - HOST_THROTTLE_MAX
        for d, _ in sorted(_host_throttle.items(), key=lambda kv: kv[1])[:surplus]:
            _host_throttle.pop(d, None)

def hote_throttle(domain: str) -> bool:
    if not domain:
        return False
    with _domain_lock:
        until = _host_throttle.get(domain)
        if until is None:
            return False
        if time.time() >= until:
            _host_throttle.pop(domain, None)
            return False
        return True

def domain_en_penalite(domain: str) -> bool:
    if not domain:
        return False
    with _domain_lock:
        return _domain_last_access.get(domain, 0.0) > time.time() + domain_min_delay(domain)

def _purger_cache_verrou_tenu() -> None:
    limite = time.time() - _DOMAIN_CACHE_TTL
    a_supprimer  = [d for d, ts in _domain_last_access.items() if ts < limite]
    for d in a_supprimer:
        _domain_last_access.pop(d, None)
        _domain_penalty_active.pop(d, None)
    if a_supprimer:
        log.debug(
            f"domain_last_access : {len(a_supprimer)} entrée(s) "
            f"expirée(s) supprimée(s)"
        )
