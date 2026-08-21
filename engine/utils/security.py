
import ipaddress
import re
import socket
from urllib.parse import urlparse

from engine.domain.exceptions import UnsafeUrlError


class DnsBlackholeError(UnsafeUrlError):
    pass

ALLOWED_SCHEMES = frozenset({"http", "https"})

BLOCKED_HOSTS = frozenset({
    "localhost", "0.0.0.0", "::", "::1",
    "metadata.google.internal",
    "169.254.169.254",
})

_PRIVATE_IP_PATTERN = re.compile(
    r"^("
    r"10\."
    r"|172\.(1[6-9]|2\d|3[01])\."
    r"|192\.168\."
    r"|127\."
    r")"
)

_FILENAME_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_FILENAME_LEN = 200

def _parse_and_guard(url: str) -> tuple[str, str]:
    if not url or not isinstance(url, str):
        raise UnsafeUrlError("URL vide ou invalide")

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise UnsafeUrlError(f"URL malformée : {e}") from e

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Schéma non autorisé : {parsed.scheme!r}")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise UnsafeUrlError("Hostname manquant")

    if hostname in BLOCKED_HOSTS:
        raise UnsafeUrlError(f"Host bloqué (SSRF) : {hostname}")

    if _PRIVATE_IP_PATTERN.match(hostname):
        raise UnsafeUrlError(f"IP privée bloquée (SSRF) : {hostname}")

    return url, hostname

def validate_external_url(url: str) -> str:
    url, hostname = _parse_and_guard(url)

    try:
        ip = ipaddress.ip_address(hostname)
        _assert_ip_globale(ip, hostname)
        return url
    except ValueError:
        pass

    legacy = _ipv4_legacy(hostname)
    if legacy is not None:
        _assert_ip_globale(legacy, hostname)
        return url

    try:
        infos = socket.getaddrinfo(hostname, None)
    except (OSError, UnicodeError, ValueError) as e:
        raise UnsafeUrlError(f"DNS irrésolvable : {hostname} ({e})") from e
    n_valides = 0
    for *_, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        _assert_ip_globale(ip, hostname, resolu=True)
        n_valides += 1
    if n_valides == 0:
        raise UnsafeUrlError(f"Aucune IP exploitable pour {hostname}")

    return url

def _ipv4_legacy(hostname: str) -> "ipaddress.IPv4Address | None":
    """Décode les encodages IPv4 hérités (décimal, octal, hexa, formes courtes).

    ``ipaddress.ip_address`` rejette ``2130706433`` / ``0177.0.0.1`` / ``0x7f.0.0.1``
    alors que la résolution système les ramène vers une IP (souvent loopback) :
    on les normalise ici pour appliquer la même barrière SSRF sans dépendre du résolveur.
    """
    try:
        packed = socket.inet_aton(hostname)
    except (OSError, ValueError):
        return None
    try:
        return ipaddress.IPv4Address(packed)
    except ipaddress.AddressValueError:
        return None

def _assert_ip_globale(
    ip: "ipaddress.IPv4Address | ipaddress.IPv6Address",
    hostname: str,
    resolu: bool = False,
) -> None:
    if (
        not ip.is_global
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        # Un nom public qui resout vers loopback/RFC1918 signe un filtrage DNS
        # (antipub de box, filtrage FAI), pas une tentative d'attaque. Le link-local
        # (169.254.169.254 : metadonnees cloud) reste un vrai cas SSRF.
        blackhole = ip.is_loopback or (
            ip.is_private and not ip.is_link_local and not ip.is_reserved
        )
        if resolu and blackhole:
            raise DnsBlackholeError(
                f"Hôte redirigé vers une adresse locale par ton DNS : {hostname} → {ip}. "
                "C'est un antipub de box ou un filtrage FAI, pas le site qui est en cause. "
                "Change de résolveur DNS (1.1.1.1 ou 8.8.8.8) ou mets ce domaine en exception."
            )
        raise UnsafeUrlError(f"IP non-globale bloquée (SSRF) : {hostname} → {ip}")

def pin_target(url: str) -> "tuple[str, str]":
    _, hostname = _parse_and_guard(url)

    try:
        ip = ipaddress.ip_address(hostname)
        _assert_ip_globale(ip, hostname)
        return hostname, hostname
    except ValueError:
        pass

    legacy = _ipv4_legacy(hostname)
    if legacy is not None:
        _assert_ip_globale(legacy, hostname)
        return hostname, str(legacy)

    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError, ValueError) as e:
        raise LookupError(f"DNS irrésolvable : {hostname}") from e

    for *_, sockaddr in infos:
        candidate = sockaddr[0]
        try:
            ipobj = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        _assert_ip_globale(ipobj, hostname, resolu=True)
        return hostname, str(ipobj)

    raise LookupError(f"Aucune IP exploitable pour {hostname}")

def is_safe_url(url: str) -> bool:
    try:
        validate_external_url(url)
        return True
    except UnsafeUrlError:
        return False

_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

def sanitize_filename(name: str) -> str:
    if not name or not isinstance(name, str):
        return "unnamed"

    safe = _FILENAME_UNSAFE.sub("_", name)

    safe = safe.replace("..", "__")

    safe = safe[:_MAX_FILENAME_LEN].strip(" .")

    if safe.split(".")[0].upper() in _WIN_RESERVED:
        safe = "_" + safe

    return safe or "unnamed"
