from engine.download.extractor.registry import canonical_host, supported_hosts
from engine.observability.metrics import Metrics


def test_par_hote_aggregates_attempts_and_success():
    m = Metrics()
    m.incr("host_attempt_video.sibnet.ru", 4)
    m.incr("host_ok_video.sibnet.ru", 3)
    m.incr("host_attempt_vudeo.io", 2)
    d = m.resume_detaille()
    assert d["par_hote"]["video.sibnet.ru"] == {"tentatives": 4, "succes": 3, "taux_succes_pct": 75}
    assert d["par_hote"]["vudeo.io"] == {"tentatives": 2, "succes": 0, "taux_succes_pct": 0}

def test_extraction_par_lien_breakdown():
    m = Metrics()
    m.incr("extract_via_ytdlp_direct", 5)
    m.incr("extract_via_network_parallel", 2)
    d = m.resume_detaille()
    assert d["extraction_par_lien"] == {"ytdlp_direct": 5, "network_parallel": 2}

def test_hotes_supportes_listed():
    d = Metrics().resume_detaille(supported_hosts=supported_hosts)
    names = {h["name"] for h in d["hotes_supportes"]}
    assert {"sibnet", "vudeo", "vidmoly", "sendvid", "doodstream"} <= names

def test_par_hote_and_lien_empty_by_default():
    d = Metrics().resume_detaille()
    assert d["par_hote"] == {}
    assert d["extraction_par_lien"] == {}


def test_hotes_degrades_flagged_below_threshold():
    m = Metrics()
    m.incr("host_attempt_bad.tld", 5)
    m.incr("host_ok_bad.tld", 1)
    m.incr("host_attempt_good.tld", 5)
    m.incr("host_ok_good.tld", 5)
    m.incr("host_attempt_new.tld", 2)
    m.incr("host_ok_new.tld", 0)
    d = m.resume_detaille()
    assert d["hotes_degrades"] == ["bad.tld"]

def test_hotes_degrades_empty_by_default():
    assert Metrics().resume_detaille()["hotes_degrades"] == []


def test_par_hote_canonique_rolls_up_cdn_mirrors():
    m = Metrics()
    m.incr("host_attempt_d000d.com", 3)
    m.incr("host_ok_d000d.com", 2)
    m.incr("host_attempt_dood.watch", 1)
    m.incr("host_ok_dood.watch", 1)
    d = m.resume_detaille(canonical_host=canonical_host)
    assert d["par_hote_canonique"]["doodstream"] == {
        "tentatives": 4, "succes": 3, "taux_succes_pct": 75,
    }

def test_par_hote_canonique_keeps_unknown_host_bare():
    m = Metrics()
    m.incr("host_attempt_weird.tld", 2)
    m.incr("host_ok_weird.tld", 1)
    d = m.resume_detaille(canonical_host=canonical_host)
    assert d["par_hote_canonique"]["weird.tld"] == {
        "tentatives": 2, "succes": 1, "taux_succes_pct": 50,
    }

def test_par_hote_canonique_empty_by_default():
    assert Metrics().resume_detaille()["par_hote_canonique"] == {}


def test_hotes_degrades_canonique_catches_fragmented_failures():
    m = Metrics()
    m.incr("host_attempt_d000d.com", 2)
    m.incr("host_ok_d000d.com", 0)
    m.incr("host_attempt_dood.watch", 2)
    m.incr("host_ok_dood.watch", 1)
    d = m.resume_detaille(canonical_host=canonical_host)
    assert d["hotes_degrades"] == []
    assert d["hotes_degrades_canonique"] == ["doodstream"]

def test_hotes_degrades_canonique_empty_by_default():
    assert Metrics().resume_detaille()["hotes_degrades_canonique"] == []
