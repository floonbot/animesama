import { expect, test } from "@playwright/test";

// « pokemon » ne trouvait pas « Pokémon », « re zero » ne trouvait pas
// « Re:Zero », et deux mots dans le desordre ne trouvaient rien. Ces tests
// jouent le filtre sur la vraie librairie de la machine : ils se calent sur un
// titre qui s'y trouve plutot que d'en supposer un.

async function ouvrirLibrairie(page) {
  await page.goto("/");
  await page.click('.nav-item[data-page="librairie"]');
  await page.waitForSelector("#lib-anime-list", { timeout: 40000 });
  if ((await page.locator(".lib-anime").count()) === 0) test.skip(true, "librairie vide");
}

async function premierTitreEnDeuxMots(page) {
  const noms = await page.locator(".lib-anime").evaluateAll((els) =>
    els.map((e) => e.dataset.nom || ""),
  );
  return noms.find((n) => n.trim().split(/\s+/).length >= 2) || "";
}

test("les mots peuvent etre tapes dans le desordre", async ({ page }) => {
  await ouvrirLibrairie(page);
  const nom = await premierTitreEnDeuxMots(page);
  test.skip(!nom, "aucun titre de deux mots dans la librairie");

  const mots = nom.trim().split(/\s+/);
  const inverse = `${mots[1]} ${mots[0]}`;

  await page.fill("#lib-search", inverse);
  await page.waitForTimeout(500);

  const visibles = await page.locator(".lib-anime:visible").evaluateAll((els) =>
    els.map((e) => e.dataset.nom),
  );
  expect(visibles).toContain(nom);
});

test("un jeton absent exclut la carte", async ({ page }) => {
  await ouvrirLibrairie(page);
  const nom = await premierTitreEnDeuxMots(page);
  test.skip(!nom, "aucun titre de deux mots dans la librairie");

  await page.fill("#lib-search", `${nom.trim().split(/\s+/)[0]} zzzqwxjamais`);
  await page.waitForTimeout(500);

  expect(await page.locator(".lib-anime:visible").count()).toBe(0);
});

test("la ponctuation tapee ne casse pas la correspondance", async ({ page }) => {
  await ouvrirLibrairie(page);
  const nom = await premierTitreEnDeuxMots(page);
  test.skip(!nom, "aucun titre de deux mots dans la librairie");

  const mots = nom.trim().split(/\s+/);
  await page.fill("#lib-search", `${mots[0]} : ${mots[1]}`);
  await page.waitForTimeout(500);

  const visibles = await page.locator(".lib-anime:visible").evaluateAll((els) =>
    els.map((e) => e.dataset.nom),
  );
  expect(visibles).toContain(nom);
});

test("le surlignage suit le premier jeton", async ({ page }) => {
  await ouvrirLibrairie(page);
  const nom = await premierTitreEnDeuxMots(page);
  test.skip(!nom, "aucun titre de deux mots dans la librairie");

  await page.fill("#lib-search", nom.trim().split(/\s+/)[0]);
  await page.waitForTimeout(500);

  expect(await page.locator(".lib-title mark").count()).toBeGreaterThan(0);
});

// Le prechargement n'existait que sur pointerover, apres 140 ms : ni le
// tactile, ni le clavier, ni un clic rapide n'en profitaient.
test("le prechargement part aussi sur pointerdown", async ({ page }) => {
  const appels = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/anime/episodes")) appels.push(r.url());
  });

  await page.goto("/");
  await page.click('.nav-item[data-page="recherche"]');
  await page.fill("#search-input", "naruto");
  await page.keyboard.press("Enter");
  // Les squelettes portent aussi .anime-card : n'attendre que ceux-la
  // reviendrait a piloter un placeholder sans data-prefetch.
  await page.waitForSelector("#search-grid .anime-card[data-prefetch]", { timeout: 40000 });
  await page.evaluate(() =>
    document.getElementById("search-suggestions")?.classList.add("hidden"),
  );

  // pointerdown seul, sans survol prealable ni clic : rien d'autre ne peut
  // avoir declenche la requete.
  await page.evaluate(() => {
    document
      .querySelector("#search-grid .anime-card[data-prefetch]")
      .dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  });

  await expect.poll(() => appels.length, { timeout: 15000 }).toBeGreaterThan(0);
});
