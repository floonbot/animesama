from engine.observability.metrics import Metrics


def test_incr_accumulates():
    m = Metrics()
    m.incr("a")
    m.incr("a", 4)
    m.incr("b", 2)
    assert m.snapshot() == {"a": 5, "b": 2}

def test_incr_zero_is_noop():
    m = Metrics()
    m.incr("a", 0)
    assert m.snapshot() == {}

def test_incr_bad_value_ignored():
    m = Metrics()
    m.incr("a", None)
    m.incr("a", "x")
    assert m.snapshot() == {}

def test_snapshot_is_copy():
    m = Metrics()
    m.incr("a")
    snap = m.snapshot()
    snap["a"] = 999
    assert m.snapshot()["a"] == 1

def test_reset():
    m = Metrics()
    m.incr("a", 3)
    m.reset()
    assert m.snapshot() == {}

def test_resume_court_format():
    m = Metrics()
    m.incr("items_termines", 2)
    m.incr("episodes_succes", 5)
    m.incr("episodes_echoues", 1)
    m.incr("episodes_skipped", 3)
    m.incr("temps_total_ms", 120000)
    m.incr("cache_hit_x", 8)
    m.incr("cache_miss_x", 2)
    r = m.resume_court()
    assert "2 telech" in r
    assert "5 ok / 1 ko / 3 skip" in r
    assert "moy 60s" in r
    assert "cache 80% hit" in r

def test_resume_court_empty_no_div_zero():
    m = Metrics()
    r = m.resume_court()
    assert "0 telech" in r and "moy 0s" in r and "cache 0% hit" in r

def test_resume_detaille_phases_and_engines():
    m = Metrics()
    m.incr("items_termines", 2)
    m.incr("temps_total_ms", 100000)
    m.incr("temps_interception_ms", 16000)
    m.incr("interception_count", 2)
    m.incr("download_ytdlp_ms", 84000)
    m.incr("download_ytdlp_attempts", 3)
    m.incr("download_ytdlp_ok", 2)
    m.incr("download_ytdlp_fail", 1)
    m.incr("items_annules", 1)
    m.incr("bytes_total", 2 * 1024 * 1024 * 1024)
    m.incr("cache_hit_x", 3)
    m.incr("cache_miss_x", 1)
    d = m.resume_detaille()
    assert d["telechargements"] == 2
    assert d["duree_moyenne_s"] == 50.0
    assert d["interception_moyenne_s"] == 8.0
    assert d["items_annules"] == 1
    assert d["go_total"] == 2.0
    assert d["par_moteur"]["ytdlp"] == {
        "tentatives": 3, "succes": 2, "echecs": 1, "temps_moyen_s": 28.0, "temps_total_s": 84.0,
        "octets": 0, "debit_mo_s": 0.0, "taux_succes_pct": 67,
    }
    assert "nm3u8dl" not in d["par_moteur"]
    assert d["cache_hit_pct"] == 75

def test_resume_detaille_empty():
    d = Metrics().resume_detaille()
    assert d["telechargements"] == 0
    assert d["interception_moyenne_s"] == 0.0
    assert d["par_moteur"] == {}
    assert d["cache_hit_pct"] == 0


def test_gauge_set_overwrites_and_max_keeps_highest():
    m = Metrics()
    m.set_gauge("g", 3)
    assert m.gauges()["g"] == 3
    m.set_gauge("g", 1)
    assert m.gauges()["g"] == 1
    m.max_gauge("h", 5)
    m.max_gauge("h", 2)
    assert m.gauges()["h"] == 5
    m.max_gauge("h", 9)
    assert m.gauges()["h"] == 9


def test_gauges_excluded_from_snapshot():
    m = Metrics()
    m.set_gauge("g", 1)
    m.incr("c", 2)
    assert m.snapshot() == {"c": 2}


def test_gauges_returns_copy():
    m = Metrics()
    m.set_gauge("g", 1)
    g = m.gauges()
    g["g"] = 99
    assert m.gauges()["g"] == 1


def test_gauge_bad_value_ignored():
    m = Metrics()
    m.set_gauge("g", None)
    m.max_gauge("h", "x")
    assert m.gauges() == {}


def test_reset_clears_gauges_and_samples():
    m = Metrics()
    m.set_gauge("g", 1)
    m.observe("lat", 2.0)
    m.reset()
    assert m.gauges() == {}
    assert m.percentiles("lat") == {}


def test_observe_percentiles_nearest_rank():
    m = Metrics()
    for v in range(1, 11):
        m.observe("lat", float(v))
    p = m.percentiles("lat")
    assert p == {"p50": 5.0, "p95": 10.0, "max": 10.0, "count": 10}


def test_percentiles_empty_when_no_samples():
    assert Metrics().percentiles("lat") == {}


def test_observe_reservoir_is_bounded():
    m = Metrics()
    for v in range(2000):
        m.observe("lat", float(v))
    assert m.percentiles("lat")["count"] <= 512


def test_resume_detaille_engine_throughput_and_success_rate():
    m = Metrics()
    m.incr("download_ytdlp_attempts", 4)
    m.incr("download_ytdlp_ok", 3)
    m.incr("download_ytdlp_fail", 1)
    m.incr("download_ytdlp_ms", 10000)
    m.incr("download_ytdlp_bytes", 10 * 1024 * 1024)
    eng = m.resume_detaille()["par_moteur"]["ytdlp"]
    assert eng["octets"] == 10 * 1024 * 1024
    assert eng["debit_mo_s"] == 1.0
    assert eng["taux_succes_pct"] == 75


def test_resume_detaille_global_rates_and_gauges():
    m = Metrics()
    m.incr("episodes_succes", 8)
    m.incr("episodes_echoues", 2)
    m.incr("bytes_total", 10 * 1024 * 1024)
    m.incr("download_ytdlp_ms", 10000)
    m.set_gauge("queue_depth_max", 7)
    d = m.resume_detaille()
    assert d["taux_succes_pct"] == 80
    assert d["debit_global_mo_s"] == 1.0
    assert d["queue_depth_max"] == 7
    assert isinstance(d["uptime_s"], int)


def test_resume_detaille_exposes_episode_and_error_tallies():
    m = Metrics()
    m.incr("episodes_succes", 5)
    m.incr("episodes_echoues", 2)
    m.incr("episodes_skipped", 3)
    m.incr("items_erreur", 1)
    m.incr("bytes_total", 1024 * 1024)
    d = m.resume_detaille()
    assert d["episodes_ok"] == 5
    assert d["episodes_ko"] == 2
    assert d["episodes_skip"] == 3
    assert d["items_erreur"] == 1
    assert d["octets_total"] == 1024 * 1024


def test_resume_detaille_http_request_counters():
    m = Metrics()
    m.incr("http_requests_total", 10)
    m.incr("http_requests_2xx", 7)
    m.incr("http_requests_3xx", 0)
    m.incr("http_requests_4xx", 2)
    m.incr("http_requests_5xx", 1)
    m.incr("http_requests_diag", 40)
    m.incr("http_requests_media", 5)
    assert m.resume_detaille()["http"] == {
        "total": 10, "diag": 40, "media": 5, "reponses_2xx": 7, "reponses_3xx": 0,
        "erreurs_4xx": 2, "erreurs_5xx": 1, "taux_erreur_pct": 30,
    }


def test_resume_detaille_http_empty():
    assert Metrics().resume_detaille()["http"] == {
        "total": 0, "diag": 0, "media": 0, "reponses_2xx": 0, "reponses_3xx": 0,
        "erreurs_4xx": 0, "erreurs_5xx": 0, "taux_erreur_pct": 0,
    }


def test_resume_detaille_request_latency_present_when_observed():
    m = Metrics()
    assert "request_s" not in m.resume_detaille()["latences"]
    for v in range(1, 11):
        m.observe("lat_request_s", float(v))
    assert m.resume_detaille()["latences"]["request_s"] == {"p50": 5.0, "p95": 10.0, "max": 10.0}


def test_resume_detaille_latences_present_only_when_observed():
    m = Metrics()
    assert m.resume_detaille()["latences"] == {}
    for v in range(1, 11):
        m.observe("lat_episode_s", float(v))
    lat = m.resume_detaille()["latences"]
    assert lat["episode_s"] == {"p50": 5.0, "p95": 10.0, "max": 10.0}
