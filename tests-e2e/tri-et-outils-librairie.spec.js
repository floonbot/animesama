import { expect, test } from "@playwright/test";

// Trois demandes tenues ensemble parce qu'elles touchent les memes barres :
//
//   - la barre de tri portait six puces pour cinq criteres, dont deux paires
//     (A→Z / Z→A) dont une seule servait a la fois. Un bouton par critere, qui
//     bascule son sens et affiche la fleche du tri courant ;
//   - Stats et Export ont quitte la barre d'outils de la librairie pour la page
//     Diagnostic, ou ils voisinent les autres chiffres de l'installation ;
//   - le Diagnostic est desormais atteignable depuis l'accueil.
//
// Le point dur du deplacement : les deux boutons prenaient la librairie deja
// chargee par sa page. Sur le Diagnostic, la carte doit aller la chercher
// elle-meme — sinon il faut passer par la Librairie d'abord, ce qui n'a aucun
// sens pour l'utilisateur.

// La librairie se peint par tranches : #lib-anime-list existe bien avant que
// toutes les cartes y soient, et _renderLibChunks rejoue le tri quand la
// derniere arrive. Comparer deux ordres sans attendre la fin, c'est mesurer une
// cible mobile — l'echec ne sort que sous la charge de la suite complete.
async function attendreListeStable(page) {
  let precedent = -1;
  await expect
    .poll(
      async () => {
        const n = await page.locator("#lib-anime-list .lib-anime").count();
        const stable = n > 0 && n === precedent;
        precedent = n;
        return stable;
      },
      { timeout: 30000, intervals: [300] },
    )
    .toBe(true);
}

async function ouvrirLibrairie(page) {
  await page.goto("/");
  await page.click('.nav-item[data-page="librairie"]');
  await page.waitForSelector("#lib-anime-list", { timeout: 30000 });
  await attendreListeStable(page);
}

async function ouvrirDiagnostic(page) {
  await page.goto("/");
  await page.click('.nav-item[data-page="diag"]');
  await page.waitForFunction(
    () => document.querySelectorAll("#diag-cards .card").length > 5,
    null,
    { timeout: 15000 },
  );
}

const nomsAffiches = (page) =>
  page.$$eval("#lib-anime-list .lib-anime", (els) => els.map((e) => e.dataset.nom || ""));

test("la barre de tri tient en cinq puces", async ({ page }) => {
  await ouvrirLibrairie(page);
  await expect(page.locator(".lib-sort-btn")).toHaveCount(5);
  await expect(page.locator(".lib-sort-btn").nth(0)).toHaveText("Défaut");
  await expect(page.locator(".lib-sort-btn").nth(2)).toHaveText("A→Z");
  await expect(page.locator(".lib-sort-btn").nth(3)).toHaveText("Taille ↓");
  await expect(page.locator(".lib-sort-btn").nth(4)).toHaveText("Éps ↓");
});

test("recliquer le tri actif inverse le sens et l'etiquette", async ({ page }) => {
  await ouvrirLibrairie(page);
  if ((await page.locator("#lib-anime-list .lib-anime").count()) < 2) {
    test.skip(true, "moins de deux animes en librairie");
  }
  const nom = page.locator('.lib-sort-btn[data-sens="az|za"]');

  await nom.dispatchEvent("click");
  await expect(nom).toHaveText("A→Z");
  await expect(nom).toHaveClass(/active/);
  await expect(nom).toHaveAttribute("aria-pressed", "true");
  const croissant = await nomsAffiches(page);

  await nom.dispatchEvent("click");
  await expect(nom).toHaveText("Z→A");
  await expect(nom).toHaveClass(/active/);
  const decroissant = await nomsAffiches(page);

  expect(decroissant.length).toBe(croissant.length);
  expect(decroissant).toEqual([...croissant].reverse());
});

test("changer de critere puis revenir retrouve le sens laisse", async ({ page }) => {
  await ouvrirLibrairie(page);
  const nom = page.locator('.lib-sort-btn[data-sens="az|za"]');
  const taille = page.locator('.lib-sort-btn[data-sens="size|size_asc"]');

  await nom.dispatchEvent("click");
  await nom.dispatchEvent("click");
  await expect(nom).toHaveText("Z→A");

  await taille.dispatchEvent("click");
  await expect(taille).toHaveClass(/active/);
  await expect(nom).not.toHaveClass(/active/);
  // L'etiquette du bouton inactif annonce ce qu'un clic ferait : le sens ou on
  // l'avait laisse, pas un retour au defaut.
  await expect(nom).toHaveText("Z→A");

  await nom.dispatchEvent("click");
  await expect(nom).toHaveText("Z→A");
  await expect(nom).toHaveClass(/active/);
});

test("taille et episodes basculent aussi leur fleche", async ({ page }) => {
  await ouvrirLibrairie(page);
  for (const [sens, bas, haut] of [
    ["size|size_asc", "Taille ↓", "Taille ↑"],
    ["eps|eps_asc", "Éps ↓", "Éps ↑"],
  ]) {
    const btn = page.locator(`.lib-sort-btn[data-sens="${sens}"]`);
    await btn.dispatchEvent("click");
    await expect(btn).toHaveText(bas);
    await btn.dispatchEvent("click");
    await expect(btn).toHaveText(haut);
  }
});

test("la barre d'outils de la librairie n'a plus Stats ni Export", async ({ page }) => {
  await ouvrirLibrairie(page);
  await expect(page.locator("#lib-export")).toHaveCount(0);
  await expect(page.locator("#lib-stats-btn")).toHaveCount(0);
});

test("le Diagnostic charge la librairie sans qu'on soit passe par sa page", async ({ page }) => {
  // Le grief a eviter : « je dois aller sur une page pour que ça charge, puis
  // aller dans une autre ». On arrive directement sur le Diagnostic.
  await ouvrirDiagnostic(page);

  const carte = page.locator("#diag-cards .card", { hasText: "Librairie" }).first();
  await expect(carte).toHaveCount(1);
  await expect(carte.locator(".diag-lib-actions button")).toHaveCount(2);

  const animes = carte.locator(".row", { hasText: "Animes" }).locator(".v");
  await expect(animes).toHaveCount(1);
  expect(Number(await animes.textContent())).toBeGreaterThan(0);
});

test("le bouton Statistiques du Diagnostic ouvre la modale", async ({ page }) => {
  await ouvrirDiagnostic(page);
  const carte = page.locator("#diag-cards .card", { hasText: "Librairie" }).first();
  await carte.getByRole("button", { name: /Statistiques/ }).click();

  const modale = page.locator("#modal-lib-stats");
  await expect(modale).toBeVisible();
  await expect(modale.locator(".stat-row", { hasText: "Total animes" })).toHaveCount(1);
});

test("le Diagnostic s'ouvre depuis l'accueil", async ({ page }) => {
  await page.goto("/");
  await page.click("#hero-diag");
  await expect(page.locator("#page-diag")).toHaveClass(/active/);
});
