import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODAL = ROOT / "web" / "static" / "js" / "pages" / "anime-modal.js"


def _handler(source: str, id_bouton: str) -> str:
    debut = source.index(f"getElementById('{id_bouton}')")
    fin = source.index("});", debut)
    return source[debut:fin]


def test_bascule_mode_selection_rebranche_la_pagination():
    src = MODAL.read_text(encoding="utf-8")

    handler = _handler(src, "btn-select-mode")

    assert "bindEpClicks(" in handler
    assert "updateSelCount()" in handler
    assert "bindPagination(" in handler


def test_selection_en_masse_ne_dispatche_plus_d_evenement():
    src = MODAL.read_text(encoding="utf-8")

    for bouton in ("btn-sel-all", "btn-sel-none"):
        handler = _handler(src, bouton)
        assert "dispatchEvent" not in handler, bouton


def test_le_garde_bulk_est_retire():
    src = MODAL.read_text(encoding="utf-8")

    assert "_bulk" not in src


def test_un_seul_listener_change_sur_les_cases():
    src = MODAL.read_text(encoding="utf-8")

    listeners = re.findall(r"addEventListener\('change'", src)

    assert len(listeners) == 1
