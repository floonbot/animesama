import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable

log = logging.getLogger("engine.observability.metrics")

RESERVOIR_MAX = 512
COUNTERS_MAX = 2000

HOST_ALERT_MIN_ATTEMPTS = 3
HOST_ALERT_SUCCESS_PCT = 30


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._samples: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._plafond_signale = False

    def incr(self, name: str, n: int = 1) -> None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            return
        if n == 0:
            return
        with self._lock:
            connu = name in self._counters
            if not connu and len(self._counters) >= COUNTERS_MAX:
                if not self._plafond_signale:
                    self._plafond_signale = True
                    log.warning(
                        "Plafond de métriques atteint (%d clés) — "
                        "les nouveaux compteurs dynamiques sont ignorés",
                        COUNTERS_MAX,
                    )
                return
            self._counters[name] = self._counters.get(name, 0) + n

    def set_gauge(self, name: str, value: float) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._gauges[name] = v

    def max_gauge(self, name: str, value: float) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        with self._lock:
            current = self._gauges.get(name)
            if current is None or v > current:
                self._gauges[name] = v

    def observe(self, name: str, value: float) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        with self._lock:
            buf = self._samples.get(name)
            if buf is None:
                buf = deque(maxlen=RESERVOIR_MAX)
                self._samples[name] = buf
            buf.append(v)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._counters)

    def gauges(self) -> dict:
        with self._lock:
            return dict(self._gauges)

    @staticmethod
    def _percentile(sorted_vals: list[float], pct: float) -> float:
        if not sorted_vals:
            return 0.0
        rank = math.ceil(pct / 100 * len(sorted_vals))
        idx = min(max(rank, 1), len(sorted_vals)) - 1
        return sorted_vals[idx]

    def percentiles(self, name: str) -> dict:
        with self._lock:
            buf = self._samples.get(name)
            vals = sorted(buf) if buf else []
        if not vals:
            return {}
        return {
            "p50": round(self._percentile(vals, 50), 1),
            "p95": round(self._percentile(vals, 95), 1),
            "max": round(vals[-1], 1),
            "count": len(vals),
        }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._samples.clear()

    def uptime_s(self) -> int:
        return int(time.monotonic() - self._t0)

    def resume_court(self) -> str:
        s = self.snapshot()
        items = s.get("items_termines", 0)
        succ = s.get("episodes_succes", 0)
        ech = s.get("episodes_echoues", 0)
        skip = s.get("episodes_skipped", 0)
        ms = s.get("temps_total_ms", 0)
        moy = (ms / items / 1000) if items else 0.0
        hits = sum(v for k, v in s.items() if k.startswith("cache_hit_"))
        miss = sum(v for k, v in s.items() if k.startswith("cache_miss_"))
        total_c = hits + miss
        taux = (100 * hits / total_c) if total_c else 0.0
        return (
            f"Cumul : {items} telech · {succ} ok / {ech} ko / {skip} skip "
            f"· moy {moy:.0f}s · cache {taux:.0f}% hit"
        )

    def resume_detaille(
        self,
        supported_hosts: Callable[[], list] | None = None,
        canonical_host: Callable[[str], str] | None = None,
    ) -> dict:
        s = self.snapshot()
        g = self.gauges()

        def moy_s(total_ms_key: str, count_key: str) -> float:
            c = s.get(count_key, 0)
            return round(s.get(total_ms_key, 0) / c / 1000, 1) if c else 0.0

        def debit_mo_s(octets: int, ms: int) -> float:
            return round(octets / (ms / 1000) / 1024 / 1024, 2) if ms else 0.0

        octets = s.get("bytes_total", 0)
        succes_ep = s.get("episodes_succes", 0)
        echoues_ep = s.get("episodes_echoues", 0)
        total_ep = succes_ep + echoues_ep
        engine_ms = sum(s.get(f"download_{e}_ms", 0) for e in ("ytdlp", "nm3u8dl", "ffmpeg"))
        out = {
            "telechargements": s.get("items_termines", 0),
            "episodes_ok": succes_ep,
            "episodes_ko": echoues_ep,
            "episodes_skip": s.get("episodes_skipped", 0),
            "items_annules": s.get("items_annules", 0),
            "items_erreur": s.get("items_erreur", 0),
            "octets_total": octets,
            "go_total": round(octets / 1024 / 1024 / 1024, 2),
            "duree_moyenne_s": moy_s("temps_total_ms", "items_termines"),
            "interception_moyenne_s": moy_s("temps_interception_ms", "interception_count"),
            "debit_global_mo_s": debit_mo_s(octets, engine_ms),
            "taux_succes_pct": round(100 * succes_ep / total_ep) if total_ep else 0,
            "uptime_s": self.uptime_s(),
            "queue_depth_max": int(g.get("queue_depth_max", 0)),
            "par_moteur": {},
            "latences": {},
        }
        for eng in ("ytdlp", "nm3u8dl", "ffmpeg"):
            att = s.get(f"download_{eng}_attempts", 0)
            if att:
                eng_ms = s.get(f"download_{eng}_ms", 0)
                eng_octets = s.get(f"download_{eng}_bytes", 0)
                out["par_moteur"][eng] = {
                    "tentatives": att,
                    "succes": s.get(f"download_{eng}_ok", 0),
                    "echecs": s.get(f"download_{eng}_fail", 0),
                    "temps_moyen_s": moy_s(f"download_{eng}_ms", f"download_{eng}_attempts"),
                    "temps_total_s": round(eng_ms / 1000, 1),
                    "octets": eng_octets,
                    "debit_mo_s": debit_mo_s(eng_octets, eng_ms),
                    "taux_succes_pct": round(100 * s.get(f"download_{eng}_ok", 0) / att),
                }
        for key, label in (
            ("lat_episode_s", "episode_s"),
            ("lat_ytdlp_s", "ytdlp_s"),
            ("lat_nm3u8dl_s", "nm3u8dl_s"),
            ("lat_ffmpeg_s", "ffmpeg_s"),
            ("lat_request_s", "request_s"),
        ):
            p = self.percentiles(key)
            if p:
                out["latences"][label] = {"p50": p["p50"], "p95": p["p95"], "max": p["max"]}
        hits = sum(v for k, v in s.items() if k.startswith("cache_hit_"))
        miss = sum(v for k, v in s.items() if k.startswith("cache_miss_"))
        total_c = hits + miss
        out["cache_hit_pct"] = round(100 * hits / total_c) if total_c else 0

        par_hote: dict[str, dict] = {}
        for key, att in s.items():
            if not key.startswith("host_attempt_"):
                continue
            host = key[len("host_attempt_"):]
            ok = s.get(f"host_ok_{host}", 0)
            par_hote[host] = {
                "tentatives": att,
                "succes": ok,
                "taux_succes_pct": round(100 * ok / att) if att else 0,
            }
        out["par_hote"] = par_hote
        out["hotes_degrades"] = [
            h for h, d in par_hote.items()
            if d["tentatives"] >= HOST_ALERT_MIN_ATTEMPTS
            and d["taux_succes_pct"] < HOST_ALERT_SUCCESS_PCT
        ]
        par_hote_canon = self._par_hote_canonique(par_hote, canonical_host)
        out["par_hote_canonique"] = par_hote_canon
        out["hotes_degrades_canonique"] = [
            h for h, d in par_hote_canon.items()
            if d["tentatives"] >= HOST_ALERT_MIN_ATTEMPTS
            and d["taux_succes_pct"] < HOST_ALERT_SUCCESS_PCT
        ]
        out["extraction_par_lien"] = {
            k[len("extract_via_"):]: v for k, v in s.items() if k.startswith("extract_via_")
        }
        if supported_hosts is None:
            out["hotes_supportes"] = []
        else:
            try:
                out["hotes_supportes"] = supported_hosts()
            except Exception:
                out["hotes_supportes"] = []
        req_total = s.get("http_requests_total", 0)
        req_4xx = s.get("http_requests_4xx", 0)
        req_5xx = s.get("http_requests_5xx", 0)
        out["http"] = {
            "total": req_total,
            "diag": s.get("http_requests_diag", 0),
            "media": s.get("http_requests_media", 0),
            "reponses_2xx": s.get("http_requests_2xx", 0),
            "reponses_3xx": s.get("http_requests_3xx", 0),
            "erreurs_4xx": req_4xx,
            "erreurs_5xx": req_5xx,
            "taux_erreur_pct": round(100 * (req_4xx + req_5xx) / req_total) if req_total else 0,
        }
        return out

    @staticmethod
    def _par_hote_canonique(
        par_hote: dict[str, dict],
        canonical_host: Callable[[str], str] | None = None,
    ) -> dict[str, dict]:
        if canonical_host is None:
            return {}
        roll: dict[str, dict] = {}
        for host, d in par_hote.items():
            name = canonical_host(host) or host
            agg = roll.setdefault(name, {"tentatives": 0, "succes": 0})
            agg["tentatives"] += d["tentatives"]
            agg["succes"] += d["succes"]
        for agg in roll.values():
            t = agg["tentatives"]
            agg["taux_succes_pct"] = round(100 * agg["succes"] / t) if t else 0
        return roll

metrics = Metrics()
