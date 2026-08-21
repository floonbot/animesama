import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

// Deux gardes, avant et apres la suite.
//
// 1. Le bundle servi doit etre celui du disque. Depuis que reuseExistingServer
//    est a false, Playwright demarre toujours son propre serveur : il ne reste
//    qu'une cause a un ecart, un « npm run build » oublie apres une edition JS.
//    On mesurerait sinon l'ancien paquet en croyant mesurer le nouveau.
//
// 2. Rien de data/, downloads/ ou scans/ ne doit avoir bouge. Meme garde-fou que
//    tests/conftest.py : le serveur e2e ecrivait dans les donnees reelles
//    (journal de l'app, cache des episodes, base de la file), et la rotation de
//    app.log (backupCount=3) finissait par emporter l'historique. La prevention
//    est ANIMESAMA_DATA_DIR, pose sur le webServer ; cette detection la double,
//    parce qu'elle couvre aussi ce qui ecrirait sous la racine sans passer par
//    DATA_DIR.

const empreinte = (buf) => createHash("sha1").update(buf).digest("hex").slice(0, 16);

// Ancre sur la racine du depot, pas sur le repertoire courant : une empreinte
// prise au mauvais endroit ne verrait rien et le garde-fou serait decoratif.
const RACINE = join(import.meta.dirname, "..");
const SURVEILLES = ["data", "downloads", "scans"].map((n) => join(RACINE, n));

function empreinteDossier(racine) {
  const out = new Map();
  const descendre = (dir) => {
    let entrees;
    try {
      entrees = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entrees) {
      const chemin = join(dir, e.name);
      if (e.isDirectory()) descendre(chemin);
      else if (e.isFile()) {
        try {
          const st = statSync(chemin);
          out.set(relative(racine, chemin), `${st.size}/${st.mtimeMs}`);
        } catch {
          /* disparu en cours de parcours : rien a comparer */
        }
      }
    }
  };
  descendre(racine);
  return out;
}

function ecarts(avant, apres) {
  const lignes = [];
  for (const cle of [...new Set([...avant.keys(), ...apres.keys()])].sort()) {
    const a = avant.get(cle);
    const b = apres.get(cle);
    if (a === b) continue;
    if (a === undefined) lignes.push(`    + cree    ${cle}  (${b.split("/")[0]} o)`);
    else if (b === undefined) lignes.push(`    - efface  ${cle}`);
    else lignes.push(`    ~ modifie ${cle}  (${a.split("/")[0]} -> ${b.split("/")[0]} o)`);
  }
  return lignes;
}

export default async function verifierServeur(config) {
  const base = config.projects[0]?.use?.baseURL || "http://127.0.0.1:7843";
  const url = `${base}/dist/app.js`;

  let servi;
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    servi = Buffer.from(await r.arrayBuffer());
  } catch (e) {
    throw new Error(`Impossible de lire ${url} : ${e.message}`);
  }

  const disque = readFileSync(join(RACINE, "web/static/dist/app.js"));
  if (empreinte(servi) === empreinte(disque)) {
    const avant = new Map(SURVEILLES.map((n) => [n, empreinteDossier(n)]));
    return () => {
      const fautes = [];
      for (const nom of SURVEILLES) {
        const lignes = ecarts(avant.get(nom), empreinteDossier(nom));
        if (lignes.length) fautes.push(`  ${relative(RACINE, nom)}/ :\n${lignes.join("\n")}`);
      }
      // La copie n'est pas effacee ici : le serveur n'est tue qu'apres nous et
      // garde ses .db ouverts, et c'est la que vit son journal quand un test
      // tombe. playwright.config.js balaie celles de plus d'une heure.
      if (!fautes.length) return;
      throw new Error(
        "\n=================== ISOLATION VIOLEE ===================\n" +
          "La suite e2e a ecrit dans les donnees reelles :\n" +
          fautes.join("\n") +
          "\n-> le serveur doit tourner avec ANIMESAMA_DATA_DIR" +
          "\n   (pose sur webServer.env dans playwright.config.js)." +
          `\n   copie de travail de ce run : ${process.env.ANIMESAMA_E2E_DATA}\n`,
      );
    };
  }

  throw new Error(
    `Le serveur sur ${base} ne sert PAS le bundle de ce dépôt.\n` +
    `  servi  : ${empreinte(servi)} (${servi.length} octets)\n` +
    `  disque : ${empreinte(disque)} (${disque.length} octets)\n\n` +
    `Cause la plus fréquente : il manque « npm run build » après une édition JS.\n` +
    `  → node build.mjs, puis relance la suite.\n\n` +
    `Si le bundle est à jour, c'est qu'un autre serveur répond sur ce port — par\n` +
    `exemple l'application INSTALLÉE, qui sert le sien depuis %LOCALAPPDATA%.\n` +
    `  → ferme AnimeSama.exe, ou lance la suite sur un autre port :\n` +
    `      PORT=7844 npx playwright test`,
  );
}
