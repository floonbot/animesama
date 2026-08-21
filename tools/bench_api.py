"""Micro-benchmark reproductible des routes chaudes de l'API.

Mesure la latence bout-en-bout a travers toute la pile ASGI (HostGuard,
RequestContext, RequestMetrics, gzip) sur les routes que le
front appelle en boucle : statut de la file, reglages, librairie en cache.
Aucun reseau reel ni scraping : la librairie est servie depuis son cache TTL.

Usage : python tools/bench_api.py [iterations]
Deterministe a bruit d'OS pres. A lancer AVANT et APRES une optimisation.
"""

import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = os.path.join(tempfile.gettempdir(), "as_bench_api")
os.environ.setdefault("DOWNLOADS_DIR", os.path.join(_TMP, "downloads"))
os.environ.setdefault("SCANS_DIR", os.path.join(_TMP, "scans"))

from fastapi.testclient import TestClient  # noqa: E402

from engine.config.settings import HOST, PORT  # noqa: E402
from engine.library import scanner  # noqa: E402
from web.api.app import create_app  # noqa: E402

ROUTES = (
    ("/api/download/status", "file d'attente"),
    ("/api/settings", "reglages"),
    ("/api/anime/librairie", "librairie (cache)"),
    ("/api/anime/covers", "covers"),
)


def _amorcer_librairie(n_animes: int = 120, n_eps: int = 24) -> None:
    animes = [
        {
            "nom": f"Anime {i}",
            "saisons": [
                {
                    "nom": "Saison 01",
                    "episodes": [
                        {
                            "nom": f"Anime {i} S01E{j:03d} VOSTFR",
                            "fichier": f"D:/downloads/Anime {i}/Saison 01/E{j:03d}.mkv",
                            "taille": 420.5,
                            "mtime": 1_750_000_000 + j,
                        }
                        for j in range(1, n_eps + 1)
                    ],
                }
            ],
            "total_eps": n_eps,
            "total_size": 9.8,
        }
        for i in range(n_animes)
    ]
    scanner.librairie_cache_set({"animes": animes, "total": n_animes, "tronque": False})


def _mesurer(client: TestClient, path: str, n: int) -> tuple[float, float]:
    headers = {"host": f"{HOST}:{PORT}"}
    client.get(path, headers=headers)
    echantillons = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = client.get(path, headers=headers)
        echantillons.append((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            raise SystemExit(f"{path} -> HTTP {r.status_code}")
    echantillons.sort()
    p50 = statistics.median(echantillons)
    p95 = echantillons[min(len(echantillons) - 1, int(len(echantillons) * 0.95))]
    return p50, p95


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    app = create_app()
    with TestClient(app) as client:
        _amorcer_librairie()
        print(f"iterations={n} par route · pile ASGI complete\n")
        for path, label in ROUTES:
            p50, p95 = _mesurer(client, path, n)
            print(f"{label:<22} {path:<28} p50={p50:6.2f} ms  p95={p95:6.2f} ms")


if __name__ == "__main__":
    main()
