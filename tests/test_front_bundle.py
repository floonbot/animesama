import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"
INDEX = STATIC / "index.html"
SPEC = ROOT / "packaging" / "anime_sama.spec"


def _embarque_par_la_spec(rel: str) -> bool:
    if rel.endswith(".map") or rel.endswith("metafile.json"):
        return False
    return rel.split(os.sep)[0] != "js"


def _refs_locales(html: str) -> list[str]:
    refs = re.findall(r'(?:src|href)="(/[^"]+)"', html)
    return [r.split("?")[0] for r in refs]


def test_index_charge_le_bundle_et_pas_les_sources():
    html = INDEX.read_text(encoding="utf-8")

    scripts = re.findall(r'<script[^>]*\ssrc="([^"]+)"', html)

    assert "/dist/app.js" in scripts
    assert not [s for s in scripts if s.startswith("/js/")]


def test_index_ne_precharge_plus_les_modules_sources():
    html = INDEX.read_text(encoding="utf-8")

    preloads = re.findall(r'<link[^>]*rel="modulepreload"[^>]*href="([^"]+)"', html)

    assert preloads == ["/dist/app.js"]


def test_le_spec_embarque_le_dossier_dist():
    spec = SPEC.read_text(encoding="utf-8")

    assert 'if _rel.split(os.sep)[0] == "dist"' not in spec
    assert "_STATIC" in spec


def test_package_json_declare_esbuild():
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert pkg["private"] is True
    assert pkg["type"] == "module"
    assert "esbuild" in pkg["devDependencies"]
    assert pkg["scripts"]["build"] == "node build.mjs"


def test_build_mjs_hashe_les_chunks_et_ecrit_un_metafile():
    build = (ROOT / "build.mjs").read_text(encoding="utf-8")

    assert 'chunkNames: "chunks/[name]-[hash]"' in build
    assert "metafile: true" in build
    assert "metafile.json" in build


def test_build_exe_construit_le_front_avant_pyinstaller():
    bat = (ROOT / "packaging" / "build_exe.bat").read_text(encoding="utf-8", errors="replace")

    i_bundle = bat.find("build.mjs")
    i_pyinstaller = bat.find("PyInstaller packaging")

    assert i_bundle != -1
    assert i_pyinstaller != -1
    assert i_bundle < i_pyinstaller


def test_build_de_distribution_sans_sourcemap():
    build = (ROOT / "build.mjs").read_text(encoding="utf-8")
    bat = (ROOT / "packaging" / "build_exe.bat").read_text(encoding="utf-8", errors="replace")

    assert 'process.argv.includes("--dist")' in build
    assert "sourcemap: !distribution" in build
    assert "build.mjs --dist" in bat
    assert "--sourcemap" not in bat


def test_les_map_sont_exclues_donc_le_bundle_livre_n_y_renvoie_pas():
    dist = STATIC / "dist"
    if not (dist / "app.js").exists():
        import pytest

        pytest.skip("bundle absent — lancer npm run build")

    spec = SPEC.read_text(encoding="utf-8")
    assert '_rel.endswith(".map")' in spec

    porteurs = [
        f.relative_to(dist)
        for f in dist.rglob("*.js")
        if "sourceMappingURL" in f.read_text(encoding="utf-8", errors="replace")
    ]
    orphelins = [p for p in porteurs if not (dist / (str(p) + ".map")).exists()]
    assert orphelins == []


def test_le_diagnostic_n_a_plus_son_propre_point_d_entree():
    build = (ROOT / "build.mjs").read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")

    assert "diag.js" not in build
    assert not (STATIC / "diag.html").exists()
    assert not (STATIC / "css" / "diag.css").exists()
    assert 'if _rel.split(os.sep)[0] == "js"' in spec


def test_le_tampon_de_build_est_embarque_par_la_spec():
    """Il vit dans web/static pour etre embarque sans regle dediee : si un filtre de
    la spec l'excluait, le paquet installe ne saurait plus dire de quand il date."""
    from engine.version import TAMPON_NOM

    assert _embarque_par_la_spec(TAMPON_NOM)
    assert TAMPON_NOM != "metafile.json"
    assert not TAMPON_NOM.endswith(".map")


def test_index_est_la_seule_page_html():
    assert [p.name for p in sorted(STATIC.glob("*.html"))] == ["index.html"]


def test_aucun_html_ne_reference_un_fichier_exclu_du_package():
    manquants = []
    for html in STATIC.glob("*.html"):
        for ref in _refs_locales(html.read_text(encoding="utf-8")):
            rel = ref.lstrip("/").replace("/", os.sep)
            cible = STATIC / rel
            if not cible.is_file():
                continue
            if not _embarque_par_la_spec(rel):
                manquants.append(f"{html.name} -> {ref}")
    assert manquants == []
