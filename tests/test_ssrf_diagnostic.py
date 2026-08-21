import socket

import pytest

from engine.domain.exceptions import UnsafeUrlError
from engine.utils import security


def _resolveur(mapping):
    def _fake(hostname, *a, **k):
        ip = mapping.get(hostname)
        if ip is None:
            raise socket.gaierror("inconnu")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _fake


def test_blackhole_dns_donne_un_message_actionnable(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", _resolveur({"box-1552-e.vmeas.cloud": "127.0.0.1"})
    )

    with pytest.raises(UnsafeUrlError) as exc:
        security.validate_external_url("https://box-1552-e.vmeas.cloud/master.m3u8")

    msg = str(exc.value)
    assert "box-1552-e.vmeas.cloud" in msg
    assert "127.0.0.1" in msg
    assert "DNS" in msg
    assert isinstance(exc.value, security.DnsBlackholeError)


def test_ip_privee_est_aussi_traitee_comme_blackhole(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolveur({"cdn.exemple.test": "192.168.1.254"}))

    with pytest.raises(security.DnsBlackholeError) as exc:
        security.validate_external_url("https://cdn.exemple.test/x.m3u8")

    assert "192.168.1.254" in str(exc.value)


def test_vrai_ssrf_metadata_reste_bloque(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolveur({"evil.test": "169.254.169.254"}))

    with pytest.raises(UnsafeUrlError) as exc:
        security.validate_external_url("http://evil.test/latest/meta-data")

    assert "169.254.169.254" in str(exc.value)
    assert not isinstance(exc.value, security.DnsBlackholeError)


def test_ip_publique_passe_toujours(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolveur({"cdn.exemple.test": "83.149.84.117"}))

    url = security.validate_external_url("https://cdn.exemple.test/master.m3u8")

    assert url == "https://cdn.exemple.test/master.m3u8"


def test_is_safe_url_reste_booleen(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolveur({"h.test": "127.0.0.1"}))

    assert security.is_safe_url("https://h.test/x") is False


def test_le_pipeline_logge_le_motif_et_le_propage(monkeypatch, caplog):
    import logging

    from engine.download import pipeline

    monkeypatch.setattr(socket, "getaddrinfo", _resolveur({"box.vmeas.cloud": "127.0.0.1"}))
    emis = []
    monkeypatch.setattr(pipeline, "_safe_emit", lambda q, ev, data: emis.append((ev, data)))

    with caplog.at_level(logging.ERROR):
        motif = pipeline._motif_url_refusee("https://box.vmeas.cloud/master.m3u8")

    assert motif is not None
    assert "box.vmeas.cloud" in motif
    assert "DNS" in motif


def test_url_saine_ne_produit_aucun_motif(monkeypatch):
    from engine.download import pipeline

    monkeypatch.setattr(socket, "getaddrinfo", _resolveur({"ok.test": "83.149.84.117"}))

    assert pipeline._motif_url_refusee("https://ok.test/master.m3u8") is None
