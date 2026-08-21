import { expect, test } from "@playwright/test";

// Le diagnostic etait une page autonome ouverte dans un onglet : seconde
// EventSource, fetch nus, CSS a part. Ces tests verrouillent les trois points
// de l'integration — navigation, flux partage, polling econome.

test("diagnostic : navigation, rendu et console propre", async ({ page }) => {
  const erreurs = [];
  page.on("console", (m) => { if (m.type() === "error") erreurs.push(m.text()); });
  page.on("pageerror", (e) => erreurs.push("pageerror: " + e.message));

  await page.goto("/");
  await page.click('.nav-item[data-page="diag"]');
  await expect(page.locator("#page-diag")).toHaveClass(/active/);
  await expect(page.locator('.nav-item[data-page="diag"]')).toHaveAttribute("aria-current", "page");

  await page.waitForFunction(
    () => document.querySelectorAll("#diag-cards .card").length > 5,
    null,
    { timeout: 15000 },
  );
  const titres = await page.locator("#diag-cards .card h2").allTextContents();
  expect(titres).toContain("État");
  expect(titres).toContain("Journal récent");

  await expect(page.locator("#diag-status-dot.ok")).toBeVisible();
  await expect(page.locator("#diag-last-update")).not.toBeEmpty();

  expect(erreurs).toEqual([]);
});

test("diagnostic : un seul flux SSE pour toute l'application", async ({ page }) => {
  // Compte les EventSource construites par *cette* page : /api/health compterait
  // aussi les autres onglets ouverts par les tests voisins.
  await page.addInitScript(() => {
    const Reel = window.EventSource;
    window.__sseUrls = [];
    window.EventSource = function (url, init) {
      window.__sseUrls.push(String(url));
      return new Reel(url, init);
    };
    window.EventSource.prototype = Reel.prototype;
    Object.assign(window.EventSource, Reel);
  });

  await page.goto("/");
  await page.click('.nav-item[data-page="diag"]');
  await page.waitForFunction(
    () => document.querySelectorAll("#diag-cards .card").length > 5,
    null,
    { timeout: 15000 },
  );

  expect(await page.evaluate(() => window.__sseUrls)).toEqual(["/api/events"]);
});

test("diagnostic : le polling s'arrete hors de la vue", async ({ page }) => {
  test.setTimeout(90000);
  await page.goto("/");
  await page.click('.nav-item[data-page="diag"]');
  await page.waitForFunction(
    () => document.querySelectorAll("#diag-cards .card").length > 5,
    null,
    { timeout: 15000 },
  );

  // L'intervalle de secours vaut 15 s : 18 s hors de la vue doivent laisser
  // l'horodatage fige, 18 s dans la vue doivent le faire bouger.
  await page.click('.nav-item[data-page="home"]');
  const fige = await page.locator("#diag-last-update").textContent();
  await page.waitForTimeout(18000);
  expect(await page.locator("#diag-last-update").textContent()).toBe(fige);

  await page.click('.nav-item[data-page="diag"]');
  await page.waitForTimeout(1000);
  const relance = await page.locator("#diag-last-update").textContent();
  await page.waitForTimeout(18000);
  expect(await page.locator("#diag-last-update").textContent()).not.toBe(relance);
});

// Le raccourci du Bureau lance l'application installee, pas le depot : cette ligne
// est le seul endroit de l'interface ou l'on voit de quand date ce qui tourne.
test("diagnostic : la carte Etat date le build en cours", async ({ page }) => {
  await page.goto("/");
  await page.click('.nav-item[data-page="diag"]');
  await page.waitForFunction(
    () => document.querySelectorAll("#diag-cards .card").length > 5,
    null,
    { timeout: 15000 },
  );

  const ligne = page.locator("#diag-cards .card").first().locator(".row", { hasText: "Build" });
  await expect(ligne).toHaveCount(1);
  const valeur = await ligne.locator(".v").textContent();
  expect(valeur.trim()).not.toBe("?");
  expect(valeur).toMatch(/sources de développement|paquet/);
});

test("diagnostic : accessible depuis la page Parametres", async ({ page }) => {
  await page.goto("/");
  await page.click("#nav-settings");
  await expect(page.locator("#page-parametres")).toHaveClass(/active/);
  await page.click("#settings-diag");
  await expect(page.locator("#page-parametres")).not.toHaveClass(/active/);
  await expect(page.locator("#page-diag")).toHaveClass(/active/);
});

test("diagnostic : atteignable au clavier", async ({ page }) => {
  await page.goto("/");
  await page.locator('.nav-item[data-page="diag"]').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#page-diag")).toHaveClass(/active/);
});
