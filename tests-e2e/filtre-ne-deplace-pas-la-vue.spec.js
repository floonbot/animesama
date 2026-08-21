import { expect, test } from "@playwright/test";

// Signale a l'usage : cliquer un filtre faisait remonter la liste en haut de
// l'ecran, ce qui fait disparaitre la barre d'outils qu'on vient d'utiliser et
// interdit d'en enchainer un second sans remonter a la main.
//
// DEUX causes, pas une :
//   1. softScrollTop, appele par deux barres sur quatre. Son seuil de 160 px
//      est franchi presque toujours (titre + stats + barre d'outils).
//   2. `listEl.innerHTML = ''` dans applySortAndFilter : vider le conteneur
//      effondre sa hauteur, le navigateur rabote scrollTop a zero et ne le
//      restaure pas quand les cartes reviennent. Retirer softScrollTop seul
//      laissait le tri sauter quand meme.
//
// PIEGE DE MESURE : `locator.click()` amene d'abord la cible dans la vue —
// il deplace donc le defilement lui-meme, et un test naif mesure Playwright
// au lieu de l'application. `dispatchEvent("click")` ne fait aucun controle
// d'actionnabilite et ne defile pas : c'est lui qui mesure l'application.

const DEFILEMENT = 500;

async function ouvrirLibrairie(page) {
  await page.goto("/");
  await page.click('.nav-item[data-page="librairie"]');
  await page.waitForSelector("#lib-anime-list", { timeout: 30000 });
}

const mesure = (page) =>
  page.evaluate(() => {
    const m = document.querySelector(".main");
    if (!m) return null;
    return { y: m.scrollTop, max: Math.max(0, m.scrollHeight - m.clientHeight) };
  });

async function descendre(page) {
  await page.evaluate((cible) => {
    const m = document.querySelector(".main");
    if (m) m.scrollTop = cible;
  }, DEFILEMENT);
  return mesure(page);
}

async function clicSansDefilementActif(page, selecteur) {
  if ((await page.locator(selecteur).count()) < 2) {
    test.skip(true, `moins de deux puces ${selecteur}`);
  }
  const avant = await descendre(page);
  if (!avant || avant.y < 100) test.skip(true, "page trop courte pour défiler");

  await page.locator(selecteur).nth(1).dispatchEvent("click");
  await page.waitForTimeout(700); // laisser aboutir un defilement doux s'il a lieu

  const apres = await mesure(page);
  // Filtrer raccourcit la liste : si la position depasse le nouveau maximum,
  // le navigateur la rabote, et ce n'est pas un defaut. Tout le reste en est un.
  const inchange = Math.abs(apres.y - avant.y) < 20;
  const colleAuMax = apres.y >= apres.max - 2;
  expect(
    inchange || colleAuMax,
    `y ${avant.y} -> ${apres.y} (max ${apres.max}) : défilement actif`,
  ).toBe(true);
}

test("librairie : trier ne déplace pas la vue", async ({ page }) => {
  // Le tri garde le meme nombre de cartes : aucun rabotage possible, tout
  // deplacement est actif.
  await ouvrirLibrairie(page);
  if ((await page.locator(".lib-sort-btn").count()) < 2) {
    test.skip(true, "pas de barre de tri");
  }
  const avant = await descendre(page);
  if (!avant || avant.y < 100) test.skip(true, "page trop courte pour défiler");

  await page.locator(".lib-sort-btn").nth(1).dispatchEvent("click");
  await page.waitForTimeout(700);

  expect(Math.abs((await mesure(page)).y - avant.y)).toBeLessThan(20);
});

test("librairie : filtrer par langue ne défile pas activement", async ({ page }) => {
  await ouvrirLibrairie(page);
  await clicSansDefilementActif(page, ".lib-lang-btn");
});

test("librairie : filtrer par type ne défile pas activement", async ({ page }) => {
  await ouvrirLibrairie(page);
  await clicSansDefilementActif(page, ".lib-type-btn");
});

test("librairie : filtrer par liste ne défile pas activement", async ({ page }) => {
  await ouvrirLibrairie(page);
  await clicSansDefilementActif(page, ".lib-liste-btn");
});

test("la barre d'outils reste sous la main après un tri", async ({ page }) => {
  // Le grief exact : enchainer un second filtre sans remonter a la main.
  await ouvrirLibrairie(page);
  if ((await page.locator(".lib-sort-btn").count()) < 2) {
    test.skip(true, "pas de barre de tri");
  }
  const barre = page.locator(".lib-toolbar").first();

  // Se placer juste sous le haut de page : la barre est visible, comme au moment
  // ou l'utilisateur la vise.
  await page.evaluate(() => {
    const m = document.querySelector(".main");
    const t = document.querySelector(".lib-toolbar");
    if (m && t) m.scrollTop = Math.max(0, t.offsetTop - 60);
  });
  await expect(barre).toBeInViewport();

  await page.locator(".lib-sort-btn").nth(1).click();
  await page.waitForTimeout(700);

  await expect(barre).toBeInViewport();
});

test("softScrollTop ne subsiste que pour la recherche", async ({ page }) => {
  const lib = await (await page.request.get("/js/pages/library.js")).text();
  const fav = await (await page.request.get("/js/pages/favorites.js")).text();
  const rech = await (await page.request.get("/js/pages/search.js")).text();

  // L'appel et l'import, pas le mot : un commentaire a le droit de le citer.
  expect(lib).not.toContain("softScrollTop(");
  expect(lib).not.toContain("utils/scroll.js");
  expect(fav).not.toContain("softScrollTop(");
  expect(fav).not.toContain("utils/scroll.js");
  // Une recherche remplace tout le contenu par un squelette : la nouvelle
  // grille peut naitre hors ecran, le geste garde son sens.
  expect(rech).toContain("softScrollTop(");
});
