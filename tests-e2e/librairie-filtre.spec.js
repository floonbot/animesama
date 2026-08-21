import { expect, test } from "@playwright/test";

// Le filtre surlignait les noms d'episodes de *toutes* les cartes, y compris
// repliees : 55 ms d'analyse HTML par frappe sur une librairie fournie, pour
// decorer du texte invisible. Il ne surligne plus que les cartes ouvertes et
// rattrape a l'ouverture — ces tests verrouillent les deux moities.

async function ouvrirLibrairie(page) {
  await page.goto("/");
  await page.click('.nav-item[data-page="librairie"]');
  await page.waitForSelector("#lib-anime-list", { timeout: 30000 });
  const carte = page.locator(".lib-anime").first();
  if ((await page.locator(".lib-anime").count()) === 0) test.skip(true, "librairie vide");
  await expect(carte).toBeVisible();
  return carte;
}

async function premierMotDUnEpisode(carte) {
  const nom = await carte.locator(".lib-ep-nom").first().textContent();
  return (nom || "").trim().split(/\s+/)[0].slice(0, 4).toLowerCase();
}

test("filtrer ne surligne pas les episodes des cartes repliees", async ({ page }) => {
  const carte = await ouvrirLibrairie(page);
  await carte.evaluate((el) => el.classList.remove("open"));
  const mot = await premierMotDUnEpisode(carte);
  test.skip(!mot, "aucun nom d'episode exploitable");

  await page.fill("#lib-search", mot);
  await page.waitForTimeout(400);

  const marks = await carte.locator(".lib-ep-nom mark").count();
  expect(marks).toBe(0);
});

test("ouvrir une carte pendant un filtre applique le surlignage", async ({ page }) => {
  const carte = await ouvrirLibrairie(page);
  await carte.evaluate((el) => el.classList.remove("open"));
  const mot = await premierMotDUnEpisode(carte);
  test.skip(!mot, "aucun nom d'episode exploitable");

  await page.fill("#lib-search", mot);
  await page.waitForTimeout(400);
  expect(await carte.locator(".lib-ep-nom mark").count()).toBe(0);

  await carte.locator(".lib-header-left").click();
  await page.waitForTimeout(300);

  // Les episodes vivent dans un <details> replie : on verifie leur presence
  // dans le DOM, pas leur visibilite a l'ecran.
  expect(await carte.locator(".lib-ep-nom mark").count()).toBeGreaterThan(0);
});

test("effacer le filtre retire le surlignage de la carte ouverte", async ({ page }) => {
  const carte = await ouvrirLibrairie(page);
  const mot = await premierMotDUnEpisode(carte);
  test.skip(!mot, "aucun nom d'episode exploitable");

  await carte.locator(".lib-header-left").click();
  await page.fill("#lib-search", mot);
  await page.waitForTimeout(400);
  expect(await carte.locator(".lib-ep-nom mark").count()).toBeGreaterThan(0);

  await page.fill("#lib-search", "");
  await page.waitForTimeout(400);
  expect(await carte.locator(".lib-ep-nom mark").count()).toBe(0);
});

test("le nom de l'episode reste intact apres surlignage puis effacement", async ({ page }) => {
  const carte = await ouvrirLibrairie(page);
  const cible = carte.locator(".lib-ep-nom").first();
  const avant = (await cible.textContent()) || "";
  const mot = avant.trim().split(/\s+/)[0].slice(0, 4).toLowerCase();
  test.skip(!mot, "aucun nom d'episode exploitable");

  await carte.locator(".lib-header-left").click();
  await page.fill("#lib-search", mot);
  await page.waitForTimeout(400);
  await page.fill("#lib-search", "");
  await page.waitForTimeout(400);

  expect(((await cible.textContent()) || "").trim()).toBe(avant.trim());
});

// Le placeholder promet « Filtrer par anime ou episode (ex: E03) ». Une requete
// qui ne matche que des noms d'episodes masquait pourtant toutes les cartes :
// hors filtre langue/type, showCard ne regardait que le nom de l'anime.
async function jetonDEpisodeAbsentDuTitre(page) {
  const cartes = page.locator(".lib-anime");
  const n = Math.min(await cartes.count(), 8);
  for (let i = 0; i < n; i++) {
    const carte = cartes.nth(i);
    const nomAnime = (await carte.getAttribute("data-nom")) || "";
    const nomEp = (await carte.locator(".lib-ep-nom").first().textContent()) || "";
    const m = /S\d{1,3}E\d{1,4}/i.exec(nomEp);
    if (!m) continue;
    const jeton = m[0].toLowerCase();
    if (!nomAnime.includes(jeton)) return { carte, jeton };
  }
  return { carte: null, jeton: "" };
}

test("filtrer sur un nom d'episode garde la carte visible", async ({ page }) => {
  await ouvrirLibrairie(page);
  const { carte, jeton } = await jetonDEpisodeAbsentDuTitre(page);
  test.skip(!carte, "aucun episode numerote exploitable");

  await page.fill("#lib-search", jeton);
  await page.waitForTimeout(400);

  await expect(carte).toBeVisible();
  await expect(page.locator("#lib-empty-filter:not(.hidden)")).toHaveCount(0);
});

test("filtrer sur un nom d'episode masque les animes sans cet episode", async ({ page }) => {
  await ouvrirLibrairie(page);
  const { carte, jeton } = await jetonDEpisodeAbsentDuTitre(page);
  test.skip(!carte, "aucun episode numerote exploitable");

  await page.fill("#lib-search", jeton);
  await page.waitForTimeout(400);

  const visibles = await page.locator(".lib-anime:visible").count();
  const total = await page.locator(".lib-anime").count();
  expect(visibles).toBeGreaterThan(0);
  expect(visibles).toBeLessThanOrEqual(total);
});

test("filtrer sur une chaine absente partout masque bien tout", async ({ page }) => {
  await ouvrirLibrairie(page);

  await page.fill("#lib-search", "zzzqwxjamais");
  await page.waitForTimeout(400);

  expect(await page.locator(".lib-anime:visible").count()).toBe(0);
  await expect(page.locator("#lib-empty-filter")).toBeVisible();
});

test("le titre de l'anime reste surligne, lui", async ({ page }) => {
  const carte = await ouvrirLibrairie(page);
  const titre = (await carte.locator(".lib-title").first().textContent()) || "";
  const mot = titre.trim().split(/\s+/)[0].slice(0, 4).toLowerCase();
  test.skip(!mot, "aucun titre exploitable");

  await page.fill("#lib-search", mot);
  await page.waitForTimeout(400);

  await expect(carte.locator(".lib-title mark").first()).toBeVisible();
});
