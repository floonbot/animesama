import asyncio

import engine.library.scanner as scanner
from engine.library import coherence


def _two_animes():
    return {
        "animes": [
            {"nom": "A", "saisons": [{"nom": "Saison 01", "episodes": [{}]}]},
            {"nom": "B", "saisons": [{"nom": "Saison 01", "episodes": [{}]}]},
        ]
    }


def test_coherence_survives_one_raising_check(monkeypatch):
    monkeypatch.setattr(scanner, "scan_librairie_sync", _two_animes)

    def _canon(nom):
        if nom == "A":
            raise RuntimeError("boom")
        return {"matched": True, "finished": True, "episodes": 12}

    monkeypatch.setattr(coherence, "canon_saison1", _canon)

    out = asyncio.run(coherence.verifier_coherence_librairie())

    assert isinstance(out, dict)
    assert out["verifies"] >= 1
    assert out["total"] == 2


def test_coherence_survives_non_dict_cache_entry(monkeypatch):
    monkeypatch.setattr(scanner, "scan_librairie_sync", _two_animes)

    def _canon(nom):
        if nom == "A":
            return "corrupted-cache-string"
        return {"matched": True, "finished": True, "episodes": 12}

    monkeypatch.setattr(coherence, "canon_saison1", _canon)

    out = asyncio.run(coherence.verifier_coherence_librairie())

    assert isinstance(out, dict)
    assert out["total"] == 2
