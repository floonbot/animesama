import { expect, test } from "@playwright/test";

// Les cartes etaient des <fieldset>/<legend>. Le navigateur place le legend sur
// la bordure haute du fieldset, hors de son padding : mesure a 1280 px, titre a
// 0 px du bord haut de sa carte, contre 21 px pour la carte « Compte », qui est
// un bloc normal. Les cinq cartes sont desormais des <section role="group">.

const CARTES = "#page-parametres .set-groupe";

async function ouvrir(page, largeur) {
  await page.setViewportSize({ width: largeur, height: 1000 });
  await page.goto("/");
  await page.click("#nav-settings");
  await expect(page.locator("#page-parametres")).toHaveClass(/active/);
  await page.waitForTimeout(300);
}

// L'alignement se juge a la largeur reelle : les deux qui comptent ici.
for (const largeur of [2294, 1280]) {
  test(`a ${largeur}px, chaque titre est dans le padding de sa carte`, async ({ page }) => {
    await ouvrir(page, largeur);

    const ecarts = await page.$$eval(CARTES, (cartes) => cartes.map((c) => {
      const t = c.querySelector(".set-legende");
      return +(t.getBoundingClientRect().top - c.getBoundingClientRect().top).toFixed(1);
    }));

    expect(ecarts.length).toBe(6);
    // Toutes les cartes au meme retrait : plus de titre a cheval sur la bordure.
    expect(new Set(ecarts).size).toBe(1);
    expect(ecarts[0]).toBeGreaterThan(15);
  });

  test(`a ${largeur}px, le titre s'aligne sur le contenu de sa carte`, async ({ page }) => {
    await ouvrir(page, largeur);

    const ecarts = await page.$$eval("#settings-form .set-groupe", (cartes) => cartes.map((c) => {
      const t = c.querySelector(".set-legende");
      const premier = c.querySelector(".form-group");
      return +(t.getBoundingClientRect().left - premier.getBoundingClientRect().left).toFixed(1);
    }));

    for (const e of ecarts) expect(Math.abs(e)).toBeLessThan(1);
  });
}

test("le groupe reste annonce par son intitule", async ({ page }) => {
  await ouvrir(page, 1280);

  const cartes = await page.$$eval(CARTES, (els) => els.map((e) => ({
    role: e.getAttribute("role"),
    pointe: e.getAttribute("aria-labelledby"),
    idTitre: e.querySelector(".set-legende")?.id || "",
  })));

  for (const c of cartes) {
    expect(c.role).toBe("group");
    expect(c.pointe).toBeTruthy();
    expect(c.pointe).toBe(c.idTitre);
  }
});

test("l'emoji est decoratif et separe du mot", async ({ page }) => {
  await ouvrir(page, 1280);

  const icones = page.locator(`${CARTES} .set-legende-icone`);
  await expect(icones).toHaveCount(6);

  const infos = await page.$$eval(`${CARTES} .set-legende-icone`, (els) => els.map((e) => ({
    cache: e.getAttribute("aria-hidden"),
    // L'ecart vient du gap du conteneur, pas d'une espace dans le texte.
    interlettre: getComputedStyle(e).letterSpacing,
    ecart: +(e.nextSibling
      ? e.parentElement.getBoundingClientRect().left : 0).toFixed(0) >= 0,
  })));
  for (const i of infos) {
    expect(i.cache).toBe("true");
    expect(i.interlettre).toBe("normal");
  }

  const gap = await page.locator(`${CARTES} .set-legende`).first()
    .evaluate((e) => getComputedStyle(e).columnGap);
  expect(parseFloat(gap)).toBeGreaterThan(0);
});

test("les intitules de section quittent Syne, le titre de page la garde", async ({ page }) => {
  await ouvrir(page, 1280);

  const section = await page.locator(`${CARTES} .set-legende`).first()
    .evaluate((e) => getComputedStyle(e).fontFamily);
  const titrePage = await page.locator("#page-parametres .page-title")
    .evaluate((e) => getComputedStyle(e).fontFamily);

  expect(section).not.toMatch(/Syne/);
  expect(titrePage).toMatch(/Syne/);
});

test("toutes les sections partagent la meme typographie", async ({ page }) => {
  await ouvrir(page, 1280);

  const styles = await page.$$eval(`${CARTES} .set-legende`, (els) => els.map((e) => {
    const s = getComputedStyle(e);
    return `${s.fontFamily}|${s.fontSize}|${s.fontWeight}|${s.letterSpacing}`;
  }));
  expect(new Set(styles).size).toBe(1);
});
