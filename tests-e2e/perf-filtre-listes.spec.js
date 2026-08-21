import { test } from "@playwright/test";

// Mesure du surcout du filtre par liste sur le filtrage de la librairie.
// C3 avait gagne un facteur 10 sur ce chemin ; C12 y ajoute une lecture de Set
// par carte, et seulement quand une liste est selectionnee. Lancer avec
// MESURE=1 — c'est un banc, pas un test de non-regression.

const N_ANIMES = 400;
const N_EPS = 12;

function librairie() {
  const animes = [];
  for (let i = 0; i < N_ANIMES; i++) {
    const nom = `Anime ${i} ${["Alpha", "Beta", "Gamma", "Delta"][i % 4]}`;
    const episodes = [];
    for (let e = 1; e <= N_EPS; e++) {
      episodes.push({
        nom: `S01E${String(e).padStart(2, "0")} VOSTFR`,
        fichier: `C:/lib/${i}/${e}.mp4`,
        taille: 300,
        scan: false,
        mtime: 0,
      });
    }
    animes.push({
      nom, total_size: 3.5, total_eps: N_EPS,
      saisons: [{ nom: "Saison 1", episodes }],
    });
  }
  return { animes, total: animes.length, tronque: false };
}

function favoris() {
  const animes = [];
  for (let i = 0; i < N_ANIMES; i++) {
    const listes = i % 3 === 0 ? ["favoris", "watchlist"] : ["favoris"];
    animes.push({
      nom: `Anime ${i} ${["Alpha", "Beta", "Gamma", "Delta"][i % 4]}`,
      url: `/catalogue/anime-${i}/`, image: "", statut: "VOSTFR", listes,
    });
  }
  return { animes };
}

test("banc : cout du filtre par liste", async ({ page }) => {
  test.skip(!process.env.MESURE, "banc de mesure — lancer avec MESURE=1");
  test.setTimeout(180000);

  await page.route("**/api/anime/librairie*", (r) => r.fulfill({ json: librairie() }));
  await page.route("**/api/anime/favoris*", (r) => r.fulfill({ json: favoris() }));
  await page.route("**/api/anime/covers*", (r) => r.fulfill({ json: {} }));
  await page.route("**/api/anime/check-updates*", (r) => r.fulfill({ json: { animes: {} } }));

  await page.goto("/");
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.reload();
  await page.click('.nav-item[data-page="librairie"]');
  await page.waitForSelector("#lib-anime-list .lib-anime", { timeout: 60000 });
  await page.waitForFunction(
    (n) => document.querySelectorAll(".lib-anime").length >= n, N_ANIMES,
    { timeout: 60000 },
  );

  const mesurer = async (label) => {
    const ms = await page.evaluate(async () => {
      const input = document.getElementById("lib-search");
      const frappes = ["a", "al", "alp", "alph", "alpha", "", "b", "be", "bet", "beta"];
      const t0 = performance.now();
      for (const q of frappes) {
        input.value = q;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        await new Promise((r) => setTimeout(r, 220));
      }
      return (performance.now() - t0) / 10;
    });
    // eslint-disable-next-line no-console
    console.log(`${label} : ${ms.toFixed(1)} ms par frappe (dont 220 ms d'attente)`);
    return ms;
  };

  await mesurer("sans filtre de liste (rodage)");
  const sans = await mesurer("sans filtre de liste");

  const puce = page.locator('.lib-liste-btn[data-liste="watchlist"]');
  if (await puce.count()) {
    await puce.click();
    const avec = await mesurer("avec filtre watchlist");
    // eslint-disable-next-line no-console
    console.log(`ecart : ${(avec - sans).toFixed(1)} ms par frappe`);
  }
});
