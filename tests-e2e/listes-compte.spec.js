import { expect, test } from "@playwright/test";

// C12 — les listes du compte sont un filtre, le tri « telecharges d'abord » est
// le defaut. Le piege est dans le defaut : cliquer « Defaut » ecrivait la chaine
// vide, indistinguable d'une cle absente. Ces tests verrouillent la distinction.

const FAVORIS = {
  animes: [
    { nom: "Alpha", url: "/catalogue/alpha/", image: "", statut: "VOSTFR", listes: ["favoris"] },
    { nom: "Beta", url: "/catalogue/beta/", image: "", statut: "VOSTFR", listes: ["favoris"] },
    {
      nom: "Gamma", url: "/catalogue/gamma/", image: "", statut: "VOSTFR",
      listes: ["favoris", "watchlist"],
    },
    { nom: "Delta", url: "/catalogue/delta/", image: "", statut: "VOSTFR", listes: ["watchlist"] },
  ],
};

// Seul « Beta » est telecharge : c'est lui qui doit remonter sans aucun clic.
const LIBRAIRIE = {
  total: 1,
  tronque: false,
  animes: [{
    nom: "Beta",
    total_size: 0.1,
    total_eps: 1,
    saisons: [{ nom: "Saison 1", episodes: [{ nom: "E01", fichier: "C:/x/beta.mp4", scan: false }] }],
  }],
};

async function servirFixtures(page) {
  await page.route("**/api/anime/favoris*", (route) =>
    route.fulfill({ json: FAVORIS }));
  await page.route("**/api/anime/librairie*", (route) =>
    route.fulfill({ json: LIBRAIRIE }));
  await page.route("**/api/anime/types-favoris*", (route) =>
    route.fulfill({ json: { types: {} } }));
  await page.route("**/api/anime/covers*", (route) => route.fulfill({ json: {} }));
}

async function ouvrirFavoris(page, avantChargement) {
  await servirFixtures(page);
  await page.goto("/");
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  if (avantChargement) await page.evaluate(avantChargement);
  await page.reload();
  await page.click('.nav-item[data-page="favoris"]');
  await page.waitForSelector("#favoris-grid .anime-card", { timeout: 20000 });
}

function titres(page) {
  return page.$$eval("#favoris-grid .anime-card", (els) =>
    els.map((e) => e.getAttribute("aria-label")));
}

test("profil neuf : les telecharges apparaissent en tete, sans aucun clic", async ({ page }) => {
  await ouvrirFavoris(page);

  expect((await titres(page))[0]).toBe("Beta");
  await expect(page.locator('.fav-sort-btn[data-sort="dl"]')).toHaveClass(/active/);
});

test("un choix explicite de « Defaut » survit au changement de defaut", async ({ page }) => {
  // Ce qu'ecrivait l'ancienne version quand l'utilisateur cliquait « Defaut ».
  await ouvrirFavoris(page, () => localStorage.setItem("fav_sort", ""));

  await expect(page.locator('.fav-sort-btn[data-sort="defaut"]')).toHaveClass(/active/);
  await expect(page.locator('.fav-sort-btn[data-sort="dl"]')).not.toHaveClass(/active/);
  expect((await titres(page))[0]).toBe("Alpha");
});

test("un tri deja choisi n'est pas ecrase", async ({ page }) => {
  await ouvrirFavoris(page, () => localStorage.setItem("fav_sort", "za"));

  await expect(page.locator('.fav-sort-btn[data-sort="za"]')).toHaveClass(/active/);
  expect((await titres(page))[0]).toBe("Gamma");
});

test("une puce par liste peuplee, et aucune pour une liste vide", async ({ page }) => {
  await ouvrirFavoris(page);

  const ids = await page.$$eval(".fav-liste-btn", (els) =>
    els.map((e) => e.dataset.liste));
  expect(ids).toEqual(["favoris", "watchlist"]);
  await expect(page.locator('.fav-liste-btn[data-liste="favoris"]')).toContainText("(3)");
  await expect(page.locator('.fav-liste-btn[data-liste="watchlist"]')).toContainText("(2)");
});

test("la watchlist est atteignable en un clic et ne montre qu'elle", async ({ page }) => {
  await ouvrirFavoris(page);

  await page.click('.fav-liste-btn[data-liste="watchlist"]');
  await expect.poll(() => titres(page)).toEqual(["Gamma", "Delta"]);
  await expect(page.locator('.fav-liste-btn[data-liste="watchlist"]'))
    .toHaveAttribute("aria-pressed", "true");
});

test("le filtre de liste et le tri se combinent", async ({ page }) => {
  await ouvrirFavoris(page);

  await page.click('.fav-liste-btn[data-liste="favoris"]');
  await page.click('.fav-sort-btn[data-sort="az"]');
  await expect.poll(() => titres(page)).toEqual(["Alpha", "Beta", "Gamma"]);

  await page.click('.fav-liste-btn[data-liste="watchlist"]');
  await expect.poll(() => titres(page)).toEqual(["Delta", "Gamma"]);
});

test("le choix de liste survit a un aller-retour de page", async ({ page }) => {
  await ouvrirFavoris(page);

  await page.click('.fav-liste-btn[data-liste="watchlist"]');
  await expect.poll(() => titres(page)).toEqual(["Gamma", "Delta"]);

  await page.click('.nav-item[data-page="home"]');
  await page.click('.nav-item[data-page="favoris"]');
  await expect.poll(() => titres(page)).toEqual(["Gamma", "Delta"]);
});
