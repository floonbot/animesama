
import {
  cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, sep } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// Le serveur e2e ecrivait dans les donnees reelles de l'utilisateur : journal de
// l'application, cache des episodes, base de la file. La rotation de app.log
// (backupCount=3) finissait par emporter l'historique reel.
//
// On ne peut pas simplement pointer ANIMESAMA_DATA_DIR sur un dossier vide : la
// librairie de l'utilisateur n'est pas dans data/, elle est designee PAR data/
// (user_settings.json -> downloads_dir). Un dossier vide ferait retomber le
// serveur sur ./downloads, vide lui aussi, et une dizaine de specs se
// sauteraient en « librairie vide ». On travaille donc sur une COPIE : le
// serveur lit les memes reglages, la meme session, les memes caches, et tout ce
// qu'il ecrit atterrit dans la copie. Les 16 Mo se copient en ~0,2 s.
//
// logs/ est exclu : c'est justement ce qu'on protege, et le recopier n'apporte
// rien qu'une rotation de plus.
// Un dossier par run, jamais reutilise : le precedent peut encore etre tenu par
// un serveur que Windows n'a pas fini de liberer, et une copie survivante
// rendrait la suite non hermetique. Chaque copie porte donc le PID de son
// lanceur : on efface celles dont le processus est mort, on epargne la suite qui
// tourne peut-etre sur un autre port. L'age sert de filet quand un PID est
// recycle. Effacer en fin de run ne marcherait pas : le serveur n'est tue
// qu'apres le teardown et garde ses .db ouverts.
const PREFIXE_ISOLE = "animesama-e2e-data-";
const MARQUEUR_PID = ".e2e-runner-pid";
const AGE_FILET_MS = 3600_000;

const vivant = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM"; // vivant mais hors de portee
  }
};

for (const nom of readdirSync(tmpdir())) {
  if (!nom.startsWith(PREFIXE_ISOLE)) continue;
  const chemin = join(tmpdir(), nom);
  let enUsage = false;
  try {
    const pid = Number(readFileSync(join(chemin, MARQUEUR_PID), "utf8"));
    enUsage = Boolean(pid) && vivant(pid) && Date.now() - statSync(chemin).mtimeMs < AGE_FILET_MS;
  } catch {
    /* pas de marqueur lisible : copie d'un run termine */
  }
  if (enUsage) continue;
  try {
    rmSync(chemin, { recursive: true, force: true });
  } catch {
    /* encore verrouillee : on repassera au prochain run */
  }
}
const DATA_ISOLE = mkdtempSync(join(tmpdir(), PREFIXE_ISOLE));
cpSync(join(import.meta.dirname, "data"), DATA_ISOLE, {
  recursive: true,
  filter: (src) => !src.endsWith(`${sep}logs`) && !src.includes(`${sep}logs${sep}`),
});
writeFileSync(join(DATA_ISOLE, MARQUEUR_PID), String(process.pid));
// Lu par garde-serveur.js, pour dire ou regarder en cas de violation.
process.env.ANIMESAMA_E2E_DATA = DATA_ISOLE;

// Le port par defaut est souvent pris par une instance packagee de l'app, qui
// pointe sur d'autres dossiers de telechargement : PORT permet de lancer la
// suite contre un serveur de developpement isole sans toucher a l'existant.
const PORT = process.env.PORT || "7843";
const BASE_URL = process.env.APP_URL || `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./tests-e2e",
  // Refuse de mesurer un autre code que celui du dépôt. Voir garde-serveur.js.
  globalSetup: "./tests-e2e/garde-serveur.js",
  timeout: 30_000,
  fullyParallel: false,
  // Un seul worker : les deux projets attaquent le meme serveur, qui porte des
  // caches globaux (librairie, reglages, file). Deux navigateurs en parallele
  // s'invalidaient mutuellement et faisaient echouer par intermittence les
  // tests de rafraichissement, qui mesurent justement l'absence de redessin.
  workers: 1,
  use: {
    baseURL: BASE_URL,
    headless: true,
    trace: "on-first-retry",
  },
  // Deux moteurs, parce que les defauts divergent la ou ca compte ici :
  // l'heuristique :focus-visible sur un focus pose par programme, et le rendu
  // de input[type=range], qui n'a longtemps eu que ses regles -webkit-.
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox",  use: { ...devices["Desktop Firefox"] } },
  ],
  webServer: {
    command: "python -c \"import server; server.start_server()\"",
    url: BASE_URL,
    env: { ANIMESAMA_DATA_DIR: DATA_ISOLE },
    // Se rattacher a un serveur deja la, c'est mesurer un serveur dont on ne
    // sait rien — ni son bundle (d'ou garde-serveur.js) ni son dossier de
    // donnees, donc sans l'isolation ci-dessus. Un port occupe doit echouer
    // tout de suite, pas passer au vert sur les donnees reelles.
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
