import { expect, test } from "@playwright/test";

// L'interface ne doit pas attendre un clic sur « Actualiser » pour dire la
// verite que le serveur possede deja. Le mecanisme n'etait branche que sur le
// diagnostic : ces tests verrouillent sa generalisation — redessin quand la vue
// est devant l'utilisateur, marquage sale sinon, et rattrapage au retour.

async function ouvrirLibrairie(page) {
  await page.goto("/");
  await page.click('.nav-item[data-page="librairie"]');
  await page.waitForSelector("#lib-anime-list", { timeout: 40000 });
  if ((await page.locator(".lib-anime").count()) === 0) test.skip(true, "librairie vide");
}

// Marque le noeud courant : un rafraichissement reecrit #lib-content, donc le
// marqueur disparait. C'est le signal le plus sur qu'un rendu a bien eu lieu.
async function marquer(page) {
  await page.evaluate(() => {
    document.getElementById("lib-anime-list").dataset.temoin = "1";
  });
}

async function aEteRedessine(page) {
  return page.evaluate(
    () => document.getElementById("lib-anime-list")?.dataset.temoin !== "1",
  );
}

function signaler(page) {
  return page.evaluate(() => {
    window.dispatchEvent(
      new CustomEvent("data-changed", { detail: { sujet: "librairie" } }),
    );
  });
}

test("la librairie visible se redessine sur un changement, sans clic", async ({ page }) => {
  await ouvrirLibrairie(page);
  await marquer(page);

  await signaler(page);

  await expect.poll(() => aEteRedessine(page), { timeout: 15000 }).toBe(true);
});

test("hors de la vue, rien n'est redessine — le retour rattrape", async ({ page }) => {
  await ouvrirLibrairie(page);
  await marquer(page);

  await page.click('.nav-item[data-page="home"]');
  await signaler(page);
  await page.waitForTimeout(2500);

  // Toujours le meme noeud : on n'a pas recalcule une page que personne ne regarde.
  expect(await aEteRedessine(page)).toBe(false);

  await page.click('.nav-item[data-page="librairie"]');
  await expect.poll(() => aEteRedessine(page), { timeout: 15000 }).toBe(true);
});

test("un rafraichissement vivant n'efface pas la recherche en cours", async ({ page }) => {
  await ouvrirLibrairie(page);
  const nom = await page.locator(".lib-anime").first().getAttribute("data-nom");
  const mot = (nom || "").split(" ")[0].slice(0, 4);
  test.skip(!mot, "aucun titre exploitable");

  await page.fill("#lib-search", mot);
  await page.waitForTimeout(400);
  await marquer(page);

  await signaler(page);
  await expect.poll(() => aEteRedessine(page), { timeout: 15000 }).toBe(true);

  await expect(page.locator("#lib-search")).toHaveValue(mot);
  await expect(page.locator("#lib-search-clear")).not.toHaveClass(/hidden/);
});

test("un rafraichissement vivant conserve le tri actif", async ({ page }) => {
  await ouvrirLibrairie(page);
  // Le tri par nom est une bascule depuis que les six puces sont devenues cinq :
  // un clic donne A→Z, le second Z→A. C'est ce second sens que le redessin doit
  // retrouver — le defaut le perdrait sans qu'on le voie.
  const nom = page.locator('.lib-sort-btn[data-sens="az|za"]');
  await nom.click();
  await nom.click();
  await expect(nom).toHaveText("Z→A");
  await marquer(page);

  await signaler(page);
  await expect.poll(() => aEteRedessine(page), { timeout: 15000 }).toBe(true);

  await expect(page.locator('.lib-sort-btn[data-sort="za"]')).toHaveClass(/active/);
  await expect(page.locator('.lib-sort-btn[data-sort="za"]')).toHaveText("Z→A");
  await expect(page.locator('.lib-sort-btn[data-sort=""]')).not.toHaveClass(/active/);
});

// Le critere d'acceptation, joue de bout en bout : on sert nous-memes le flux
// SSE pour y placer un episode termine, et on verifie que la librairie ouverte
// se redessine sans qu'on ait touche a un bouton « Actualiser ».
test("un episode termine redessine la librairie, sans clic", async ({ page }) => {
  await page.route("**/api/events", (route) =>
    route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache" },
      body:
        'retry: 60000\n' +
        'data: {"type": "connected"}\n\n' +
        'event: episode_done\n' +
        'data: {"type":"episode_done","ep":"S01E001 VOSTFR","succes":true,"skipped":false}\n\n',
    }),
  );

  await ouvrirLibrairie(page);
  await marquer(page);

  await expect.poll(() => aEteRedessine(page), { timeout: 20000 }).toBe(true);
  await expect(page.locator("#lib-anime-list")).toBeVisible();
});

test("un episode ignore ou echoue ne declenche aucun redessin", async ({ page }) => {
  await page.route("**/api/events", (route) =>
    route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache" },
      body:
        'retry: 60000\n' +
        'data: {"type": "connected"}\n\n' +
        'event: episode_done\n' +
        'data: {"type":"episode_done","ep":"S01E002","succes":true,"skipped":true}\n\n' +
        'event: episode_done\n' +
        'data: {"type":"episode_done","ep":"S01E003","succes":false,"erreur":"Aucun lecteur"}\n\n',
    }),
  );

  await ouvrirLibrairie(page);
  await marquer(page);
  await page.waitForTimeout(3000);

  expect(await aEteRedessine(page)).toBe(false);
});

test("aucune erreur console pendant un rafraichissement vivant", async ({ page }) => {
  const erreurs = [];
  page.on("console", (m) => { if (m.type() === "error") erreurs.push(m.text()); });
  page.on("pageerror", (e) => erreurs.push("pageerror: " + e.message));

  await ouvrirLibrairie(page);
  await marquer(page);
  await signaler(page);
  await expect.poll(() => aEteRedessine(page), { timeout: 15000 }).toBe(true);

  expect(erreurs).toEqual([]);
});
