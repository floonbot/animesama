"""Hebergeurs qui refusent cette connexion : ecartes pour la session.

Mesure du 08/11/2026 chez l'utilisateur : tout video.sibnet.ru repond
« 403 Forbidden — Request forbidden by administrative rules », quels que soient
les en-tetes, alors que sibnet.ru repond. Un refus de l'hebergeur envers cette
adresse IP, pas une limite de debit. Traite comme un 403 ordinaire, il valait
une penalite de 90 s que l'episode suivant attendait (~70 s mesurees) avant de
reprendre le meme 403 — et chaque 403 comptait comme un « ban », d'ou la pause
anti-ban globale entre deux episodes.

Le message de yt-dlp ne dit que « HTTP Error 403 » : une requete directe sur la
page tranche, et seulement apres un 403. Les marqueurs sont ceux qu'on a vus ;
un 403 sans marqueur reste une limite de debit, traitee comme avant.
"""

import logging
import threading
import time

log = logging.getLogger("engine.download.hotes_bloques")

DUREE_BLOCAGE_S = 6 * 3600  # une IP peut etre debloquee : pas definitif
_MARQUEURS = ("forbidden by administrative rules",)
_TIMEOUT_S = 10

_bloques: dict[str, float] = {}
_verrou = threading.Lock()


def _racine(domain: str) -> str:
    return (domain or "").lower().removeprefix("www.")


def hote_bloque(domain: str) -> bool:
    d = _racine(domain)
    if not d:
        return False
    with _verrou:
        jusqua = _bloques.get(d)
        if jusqua is None:
            return False
        if jusqua <= time.time():
            _bloques.pop(d, None)
            return False
        return True


def marquer_bloque(domain: str) -> None:
    d = _racine(domain)
    if not d:
        return
    with _verrou:
        _bloques[d] = time.time() + DUREE_BLOCAGE_S
    log.warning(
        "%s refuse cette connexion (403 « administrative rules ») : écarté pendant %d h",
        d, DUREE_BLOCAGE_S // 3600,
    )


def hotes_bloques() -> list[str]:
    maintenant = time.time()
    with _verrou:
        return sorted(d for d, jusqua in _bloques.items() if jusqua > maintenant)


def sans_hotes_bloques(lecteurs: list) -> list:
    from engine.download._domain_strategy import get_domain

    return [l for l in lecteurs if not (isinstance(l, dict) and hote_bloque(get_domain(l.get("src", ""))))]


def sonder_blocage(url: str, user_agent: str = "") -> bool:
    """Rejoue la page apres un 403 : vrai si l'hebergeur refuse l'adresse elle-meme."""
    import requests

    from engine.config.settings import DEFAULT_USER_AGENT

    try:
        r = requests.get(url, headers={"User-Agent": user_agent or DEFAULT_USER_AGENT},
                         timeout=_TIMEOUT_S, allow_redirects=False)
    except requests.RequestException as e:
        log.debug("sonde de blocage impossible (%s) : %s", url[:60], e)
        return False
    if r.status_code != 403:
        return False
    corps = (r.text or "")[:2000].lower()
    return any(m in corps for m in _MARQUEURS)
