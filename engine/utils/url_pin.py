"""Epingle un hote sur l'IP deja validee, le temps d'une requete.

La garde SSRF resout le nom puis verifie l'IP ; sans epinglage, urllib3 resout
une seconde fois pour se connecter et un DNS hostile peut rendre une autre
reponse entre les deux (rebinding). On detourne donc create_connection pour lui
imposer l'IP controlee. Le tableau des epingles est *par thread* : deux
telechargements paralleles ne se marchent pas dessus.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_local = threading.local()
_install_lock = threading.Lock()
_installed = False

def _pins() -> dict[str, str]:
    pins = getattr(_local, "pins", None)
    if pins is None:
        pins = {}
        _local.pins = pins
    return pins

def install() -> None:
    global _installed
    if _installed:
        return
    with _install_lock:
        if _installed:
            return
        import urllib3.util.connection as _uc

        _orig = _uc.create_connection

        def _patched(address, *args, **kwargs):
            host, port = address
            key = host.lower() if isinstance(host, str) else host
            pinned = _pins().get(key)
            if pinned is not None:
                address = (pinned, port)
            return _orig(address, *args, **kwargs)

        _uc.create_connection = _patched
        _installed = True

@contextmanager
def pin_connection(host: str, ip: str) -> Iterator[None]:
    install()
    pins = _pins()
    key = (host or "").lower()
    previous = pins.get(key)
    pins[key] = ip
    try:
        yield
    finally:
        if previous is None:
            pins.pop(key, None)
        else:
            pins[key] = previous
