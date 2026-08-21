import asyncio
import logging
import re

from engine.scraping.anilist import canon_saison1

log = logging.getLogger("engine.library.coherence")

_RE_SAISON = re.compile(r"^\s*saison\s*0*(\d+)\s*$", re.I)

def _num_saison(nom: str):
    m = _RE_SAISON.match(nom or "")
    return int(m.group(1)) if m else None

async def verifier_coherence_librairie() -> dict:
    from engine.library.scanner import scan_librairie_sync

    librairie = await asyncio.to_thread(scan_librairie_sync)
    animes = librairie.get("animes", [])
    sem = asyncio.Semaphore(3)
    incoherents: list[dict] = []
    compteur = {"verifies": 0, "matched": 0}

    async def _check(anime: dict) -> None:
        nom = anime.get("nom", "")
        saison1 = next(
            (s for s in anime.get("saisons", []) if _num_saison(s.get("nom", "")) == 1), None
        )
        if saison1 is None:
            return
        infos = await asyncio.to_thread(canon_saison1, nom)
        compteur["verifies"] += 1
        if not isinstance(infos, dict) or not infos.get("matched") or not infos.get("finished"):
            return
        compteur["matched"] += 1
        cible = infos.get("episodes")
        if not isinstance(cible, int) or cible <= 0:
            return
        local = sum(1 for e in saison1.get("episodes", []) if not e.get("scan"))
        exces = local - cible
        if 0 < exces <= 3:
            incoherents.append({"nom": nom, "saison": 1, "local": local, "canon": cible, "exces": exces})

    async def _wrap(a: dict) -> None:
        async with sem:
            await _check(a)

    await asyncio.gather(*[_wrap(a) for a in animes], return_exceptions=True)
    incoherents.sort(key=lambda x: (-x["exces"], x["nom"].lower()))
    return {
        "incoherents": incoherents,
        "total": len(animes),
        "verifies": compteur["verifies"],
        "matched": compteur["matched"],
    }
