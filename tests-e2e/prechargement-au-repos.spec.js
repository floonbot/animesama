import { expect, test } from "@playwright/test";

// C11 a mesure que l'ouverture d'une fiche coute ~850 ms de scraping distant et
// qu'un survol prealable la ramene a ~54 ms. Precharger les cartes deja a
// l'ecran pendant que l'utilisateur ne fait rien est le levier restant.
//
// Le risque n'est pas le navigateur, c'est l'anti-ban du site. Ces tests
// verrouillent donc les trois bornes : n'agir qu'apres un temps mort, espacer,
// et plafonner. La latence distante est simulee par interception : mesurer
// contre le vrai site demanderait le compte de l'utilisateur, et rejouerait le
// 850 ms de C11 sans rien apprendre de neuf.

const LATENCE_SIMULEE = 700;

const FAVORIS = {
  animes: Array.from({ length: 12 }, (_, i) => ({
    nom: `Anime ${String(i).padStart(2, "0")}`,
    url: `https://anime-sama.fr/catalogue/anime-${i}/`,
    image: "",
    listes: ["favoris"],
  })),
};

async function monter(page, { compter }) {
  await page.route("**/api/anime/favoris*", (route) =>
    route.fulfill({ json: FAVORIS }),
  );
  await page.route("**/api/anime/episodes*", async (route) => {
    compter(route.request().url());
    await new Promise((r) => setTimeout(r, LATENCE_SIMULEE));
    await route.fulfill({
      json: { titre: "Anime", episodes: [], saisons: [], total: 0 },
    });
  });
}

async function ouvrirFavoris(page) {
  await page.goto("/");
  await page.click('.nav-item[data-page="favoris"]');
  await page.waitForSelector("[data-prefetch]", { timeout: 30000 });
}

test("au repos, le préchargement est plafonné", async ({ page }) => {
  const vues = [];
  await monter(page, { compter: (u) => vues.push(u) });
  await ouvrirFavoris(page);

  // 2 s de veille + 6 x 1,2 s d'espacement, plus une marge.
  await page.waitForTimeout(12000);

  expect(vues.length).toBeGreaterThan(0);
  expect(vues.length).toBeLessThanOrEqual(6);
});

test("l'activité de l'utilisateur repousse le préchargement", async ({ page }) => {
  const vues = [];
  await monter(page, { compter: (u) => vues.push(u) });
  await ouvrirFavoris(page);

  // Bouger sans arret : la veille de 2 s ne doit jamais arriver a terme.
  for (let i = 0; i < 12; i++) {
    await page.mouse.move(100 + (i % 5) * 10, 200 + (i % 3) * 10);
    await page.waitForTimeout(300);
  }

  expect(vues.length).toBe(0);
});

test("une carte préchargée n'est plus redemandée à l'ouverture", async ({ page }) => {
  // Mesure independante du harnais : le cache client vit dans le bundle, pas
  // dans un module reimporte. Ce qu'on observe, c'est l'absence de requete —
  // et c'est exactement ce qui economise les ~850 ms mesures au C11.
  const vues = [];
  await monter(page, { compter: (u) => vues.push(u) });
  await ouvrirFavoris(page);

  const premiere = page.locator("[data-prefetch]").first();
  const cible = await premiere.getAttribute("data-prefetch");
  const encode = encodeURIComponent(cible);

  // Balayage explicite, attendu jusqu'a son terme. Courir apres la veille de 2 s
  // laissait le balayage en cours pendant la fenetre d'observation : on
  // comptait ses requetes comme si elles venaient du clic.
  await page.evaluate(() => window.__prefetchAuRepos.balayer());
  expect(vues.filter((u) => u.includes(encode)).length).toBe(1);

  const avant = vues.length;
  await premiere.click();
  // Le clic rearme la veille ; on la relance depuis un instant connu pour que
  // la fenetre d'observation tienne entierement dans les 2 s de repos.
  await page.evaluate(() => window.__prefetchAuRepos.relancerLaVeille());
  await page.waitForTimeout(1500);

  // Aucune requete de plus, ni pour cette fiche ni pour les autres : elle sort
  // du cache client. Le plafond, lui, est verrouille par le premier cas.
  expect(vues.filter((u) => u.includes(encode)).length).toBe(1);
  expect(vues.length).toBe(avant);
});

test("le contenu arrivé après la veille est quand même préchargé", async ({ page }) => {
  // La grille des favoris attend /api/anime/librairie (favorites.js:110). Sous
  // charge, cette reponse depasse les 2 s de veille : le balayage tombe alors
  // sur une page vide, ne trouve rien — et rien ne le rearme. L'utilisateur qui
  // ne touche plus a rien ne precharge jamais cette page.
  const vues = [];
  await monter(page, { compter: (u) => vues.push(u) });
  await page.route("**/api/anime/librairie*", async (route) => {
    await new Promise((r) => setTimeout(r, 3500));
    await route.fulfill({ json: { animes: [] } });
  });
  await ouvrirFavoris(page);

  await expect.poll(() => vues.length, { timeout: 15000 }).toBeGreaterThan(0);
});

test("sans repos, la fiche est bien demandée au clic (témoin)", async ({ page }) => {
  const vues = [];
  await monter(page, { compter: (u) => vues.push(u) });
  await ouvrirFavoris(page);

  const premiere = page.locator("[data-prefetch]").first();
  const cible = await premiere.getAttribute("data-prefetch");
  const encode = encodeURIComponent(cible);

  // Agiter pour empecher tout prechargement au repos, puis cliquer aussitot.
  for (let i = 0; i < 4; i++) {
    await page.mouse.move(100 + i * 7, 200 + i * 5);
    await page.waitForTimeout(120);
  }
  expect(vues.filter((u) => u.includes(encode)).length).toBe(0);

  await premiere.click();
  await page.waitForTimeout(1500);

  // La requete part au clic : c'est la latence que le prechargement supprime.
  expect(vues.filter((u) => u.includes(encode)).length).toBeGreaterThan(0);
});
