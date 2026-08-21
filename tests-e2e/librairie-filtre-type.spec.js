import { expect, test } from "@playwright/test";

// Les boutons Tout / Animés / Scans etaient en selection exclusive stricte :
// recliquer le filtre actif ne le desarmait pas, et revenir a l'ensemble
// obligeait a viser le troisieme bouton.

async function ouvrirLibrairie(page) {
  await page.goto("/");
  await page.click('.nav-item[data-page="librairie"]');
  await page.waitForSelector("#lib-anime-list", { timeout: 30000 });
  if ((await page.locator(".lib-type-btn").count()) === 0) {
    test.skip(true, "librairie vide");
  }
}

const btnType = (page, type) => page.locator(`.lib-type-btn[data-type="${type}"]`);

test("recliquer le filtre actif revient a Tout", async ({ page }) => {
  await ouvrirLibrairie(page);

  await btnType(page, "anime").click();
  await expect(btnType(page, "anime")).toHaveClass(/active/);
  await expect(btnType(page, "")).not.toHaveClass(/active/);

  await btnType(page, "anime").click();
  await expect(btnType(page, "anime")).not.toHaveClass(/active/);
  await expect(btnType(page, "")).toHaveClass(/active/);
});

test("un seul filtre de type actif a la fois", async ({ page }) => {
  await ouvrirLibrairie(page);

  await btnType(page, "anime").click();
  await btnType(page, "scan").click();

  await expect(page.locator(".lib-type-btn.active")).toHaveCount(1);
  await expect(btnType(page, "scan")).toHaveClass(/active/);
});

test("recliquer Tout laisse Tout actif", async ({ page }) => {
  await ouvrirLibrairie(page);

  await btnType(page, "").click();
  await btnType(page, "").click();
  await expect(btnType(page, "")).toHaveClass(/active/);
  await expect(page.locator(".lib-type-btn.active")).toHaveCount(1);
});

test("l'etat du filtre est annonce par aria-pressed", async ({ page }) => {
  await ouvrirLibrairie(page);

  await btnType(page, "anime").click();
  await expect(btnType(page, "anime")).toHaveAttribute("aria-pressed", "true");
  await expect(btnType(page, "")).toHaveAttribute("aria-pressed", "false");

  await btnType(page, "anime").click();
  await expect(btnType(page, "anime")).toHaveAttribute("aria-pressed", "false");
  await expect(btnType(page, "")).toHaveAttribute("aria-pressed", "true");
});

// Les puces voisines partagent le geste : laisser le type se desarmer et pas
// la langue aurait cree une incoherence dans la meme barre d'outils.
test("le filtre de langue se desarme aussi", async ({ page }) => {
  await ouvrirLibrairie(page);
  const langues = page.locator('.lib-lang-btn:not([data-langue=""])');
  test.skip((await langues.count()) === 0, "une seule langue dans cette librairie");

  const premiere = langues.first();
  await premiere.click();
  await expect(premiere).toHaveClass(/active/);

  await premiere.click();
  await expect(premiere).not.toHaveClass(/active/);
  await expect(page.locator('.lib-lang-btn[data-langue=""]')).toHaveClass(/active/);
});

test("desarmer le filtre rend les cartes masquees", async ({ page }) => {
  await ouvrirLibrairie(page);

  await btnType(page, "scan").click();
  await page.waitForTimeout(400);
  const visibles = await page.locator(".lib-anime:visible").count();
  const posees = await page.locator(".lib-anime").count();
  test.skip(visibles === posees, "aucun scan a filtrer dans cette librairie");

  await btnType(page, "scan").click();
  await page.waitForTimeout(400);
  // La liste est rendue par tranches : on recompte au lieu de comparer a un
  // total pris avant la fin du remplissage.
  const total = await page.locator(".lib-anime").count();
  expect(await page.locator(".lib-anime:visible").count()).toBe(total);
});
