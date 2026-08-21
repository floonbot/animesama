"""`tronque` naissait dans le scanner, traversait /api/anime/librairie… et
n'était lu nulle part dans le front : au-delà de LIBRAIRIE_MAX_ANIMES le scan
s'arrête et l'utilisateur voit une librairie amputée avec un compteur faux,
sans rien qui le signale. Même défaut que `checked_at` — un signal produit,
transporté, jamais montré.
"""

from pathlib import Path

from engine.library import scanner

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_JS = ROOT / "web" / "static" / "js" / "pages" / "library.js"


def _fabriquer_animes(racine: Path, combien: int) -> None:
    for i in range(combien):
        saison = racine / f"anime-{i:04d}" / "Saison 01"
        saison.mkdir(parents=True)
        (saison / "ep.mp4").write_bytes(b"x")


def test_le_scan_signale_qu_il_a_tronque(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "LIBRAIRIE_MAX_ANIMES", 3)
    _fabriquer_animes(tmp_path, 5)

    animes, tronque = scanner._scan_un_dossier(tmp_path)

    assert tronque is True
    assert len(animes) == 3


def test_le_front_lit_le_drapeau():
    src = LIBRARY_JS.read_text(encoding="utf-8")
    debut = src.index("export async function loadLibrairie")
    corps = src[debut:src.index("_libLoadedAt = Date.now()", debut)]

    assert "tronque" in corps, "le drapeau est jeté au destructuring"


def test_le_front_affiche_un_avertissement_de_troncature():
    src = LIBRARY_JS.read_text(encoding="utf-8")

    assert "lib-tronquee" in src
    assert "LIBRAIRIE_MAX_ANIMES" not in src, "le plafond appartient au serveur"


def test_l_avertissement_cite_le_compteur_du_serveur():
    src = LIBRARY_JS.read_text(encoding="utf-8")
    debut = src.index("lib-tronquee")
    bloc = src[debut - 400:debut + 400]

    assert "tronque" in bloc
