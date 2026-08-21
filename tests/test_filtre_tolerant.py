"""Le filtre des favoris exigeait le nom exact.

« nom.toLowerCase().includes(q) » sur le nom brut : « pokemon » ne trouvait pas
« Pokémon », « re zero » ne trouvait pas « Re:Zero », et deux mots dans le
desordre ne trouvaient rien. Ces tests verrouillent le comportement, et le fait
que les quatre normalisations jumelles n'en font plus qu'une.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "static" / "js"
TEXTE = JS / "utils" / "texte.js"


def _node(script: str):
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node absent — le filtre tolerant se verifie aussi en e2e")
    r = subprocess.run(
        [exe, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _filtrer(noms: list[str], requete: str) -> list[str]:
    src = TEXTE.as_uri()
    script = f"""
import {{ normaliserTexte, jetonsRequete, correspond, rang }} from {src!r};
const noms = {json.dumps(noms)};
const jetons = jetonsRequete({json.dumps(requete)});
const gardes = noms
  .map(n => ({{ n, k: normaliserTexte(n) }}))
  .filter(x => correspond(x.k, jetons));
gardes.sort((a, b) => rang(a.k, jetons) - rang(b.k, jetons));
process.stdout.write(JSON.stringify(gardes.map(x => x.n)));
"""
    return _node(script)


CATALOGUE = [
    "Pokémon",
    "Re:Zero − Starting Life in Another World",
    "Youjo Senki",
    "Fullmetal Alchemist: Brotherhood",
    "Dragon Ball Z",
]


def test_les_accents_ne_cassent_plus_la_correspondance():
    assert _filtrer(CATALOGUE, "pokemon") == ["Pokémon"]


def test_la_ponctuation_ne_compte_pas():
    assert _filtrer(CATALOGUE, "re zero") == ["Re:Zero − Starting Life in Another World"]


def test_l_ordre_des_mots_ne_compte_pas():
    assert _filtrer(CATALOGUE, "senki youjo") == ["Youjo Senki"]


def test_les_deux_points_restent_trouvables_tels_quels():
    assert _filtrer(CATALOGUE, "alchemist brotherhood") == [
        "Fullmetal Alchemist: Brotherhood"
    ]


def test_une_requete_vide_ne_filtre_rien():
    assert _filtrer(CATALOGUE, "  ") == CATALOGUE


def test_un_jeton_absent_exclut_meme_si_l_autre_est_present():
    assert _filtrer(CATALOGUE, "dragon naruto") == []


def test_le_prefixe_passe_devant_la_sous_chaine():
    noms = ["Shingeki no Kyojin", "Kyojin Hunter"]
    assert _filtrer(noms, "kyojin") == ["Kyojin Hunter", "Shingeki no Kyojin"]


def test_la_cle_d_identite_replie_aussi_les_accents():
    """Le site ecrit « Pokémon », le dossier sur le disque peut ecrire « Pokemon » :
    sans repli, le badge « telecharge » restait eteint."""
    src = TEXTE.as_uri()
    out = _node(
        f"import {{ cleAnime }} from {src!r};"
        "process.stdout.write(JSON.stringify("
        "[cleAnime('Pokémon'), cleAnime('Pokemon'), cleAnime('Re:Zero')]));"
    )
    assert out[0] == out[1]
    assert out[2] == "rezero"


def test_une_seule_implementation_de_la_normalisation():
    doublons = []
    for f in sorted(JS.rglob("*.js")):
        if f == TEXTE:
            continue
        src = f.read_text(encoding="utf-8")
        if "function _normalise(" in src or "function _normaliser(" in src:
            doublons.append(f.relative_to(JS).as_posix())
    # sakura.js n'est pas un jumeau : il retire les suffixes de langue/saison et
    # garde les espaces, c'est une cle de cache AniList, pas un filtre.
    assert doublons == ["components/sakura.js"]


@pytest.mark.parametrize("page", ["favorites.js", "library.js"])
def test_les_pages_filtrent_par_jetons(page):
    src = (JS / "pages" / page).read_text(encoding="utf-8")
    assert "utils/texte.js" in src
    assert "jetonsRequete" in src
    assert ".nom.toLowerCase().includes(" not in src
