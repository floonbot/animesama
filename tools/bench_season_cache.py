"""Micro-benchmark reproductible du cache de page-saison (get_lecteurs_async).

Simule le téléchargement d'une saison de N épisodes. Aucun réseau réel :
http_get est remplacé par un stub qui compte les appels et dort un RTT fixe.
Compare le chemin "avant" (cache vidé avant chaque épisode = comportement
historique, un fetch par épisode) au chemin "après" (un seul fetch pour toute
la saison). Déterministe. À lancer AVANT/APRÈS pour chiffrer le gain.

Usage : python tools/bench_season_cache.py [n_episodes] [rtt_ms]
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.scraping.players as players_mod
from engine.auth.manager import auth_manager


def _season_html(n_eps: int) -> str:
    eps = ",".join(f'"https://host{i % 4}.tld/v{i}"' for i in range(n_eps))
    filler = '<div class="x"><span>lorem ipsum dolor sit amet</span></div>' * 2000
    return f"<html><body>{filler}<script>var eps1=[{eps}]</script></body></html>"


class _Resp:
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


def _bench(n_eps: int, rtt_ms: float, naive: bool) -> tuple[int, float]:
    calls = {"n": 0}
    rtt = rtt_ms / 1000.0
    html = _season_html(n_eps)

    async def stub(url, cookies):
        calls["n"] += 1
        if rtt:
            await asyncio.sleep(rtt)
        return _Resp(html)

    players_mod.http_get = stub
    auth_manager.cookies = []
    players_mod.clear_season_cache()

    async def run() -> None:
        for ep in range(1, n_eps + 1):
            if naive:
                players_mod.clear_season_cache()
            await players_mod.get_lecteurs_async(f"/catalogue/demo/saison1/vostfr?ep={ep}")

    t0 = time.perf_counter()
    asyncio.run(run())
    dt = (time.perf_counter() - t0) * 1000
    return calls["n"], dt


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    rtt = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    saved = players_mod.http_get
    try:
        nb_naif, t_naif = _bench(n, rtt, naive=True)
        nb_cache, t_cache = _bench(n, rtt, naive=False)
    finally:
        players_mod.http_get = saved
        players_mod.clear_season_cache()
    speed = t_naif / t_cache if t_cache else 0.0
    print(f"saison {n} épisodes | RTT simulé {rtt:.0f} ms/fetch | html {len(_season_html(n)) // 1024} Ko")
    print(f"  AVANT (sans cache) : {nb_naif:3d} fetch  {t_naif:9.1f} ms")
    print(f"  APRÈS (cache)      : {nb_cache:3d} fetch  {t_cache:9.1f} ms")
    print(f"  gain               : {nb_naif - nb_cache} fetch en moins · x{speed:.1f} plus rapide")


if __name__ == "__main__":
    main()
