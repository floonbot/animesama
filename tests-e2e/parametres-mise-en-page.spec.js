import { expect, test } from "@playwright/test";

// Defauts releves a l'ecran sur la page Parametres : anneau de focus autour du
// titre apres un clic, placeholder ampute, pastille de valeur sur le pouce du
// curseur, deux lignes d'aide redondantes, et quatre colonnes etirees sur un
// grand ecran.

const REGLAGES = {
  qualite: "auto",
  thread_count: 16,
  downloads_dir: "",
  scans_dir: "",
  notifications: true,
  son_notif: true,
  confirm_suppr: true,
  skip_existants: true,
  langue_defaut: "VOSTFR",
};

async function ouvrirParametres(page, reglages = REGLAGES) {
  await page.route("**/api/settings", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: reglages });
    return r.fulfill({ json: { ok: true, settings: reglages } });
  });
  await page.goto("/");
  await page.click("#nav-settings");
  await expect(page.locator("#page-parametres")).toHaveClass(/active/);
}

// --- 1. anneau de focus sur le titre de page ---------------------------------
//
// Note de mesure : les deux moteurs divergent sur :focus-visible applique a un
// focus pose par script. Chromium 151 le fait matcher des que la derniere
// interaction etait un appui touche, Firefox jamais. Les tests verrouillent
// donc le mecanisme que le code controle — la classe — et ne verifient
// l'anneau lui-meme que la ou le moteur le dessine.

const anneau = (loc) => loc.evaluate((el) => getComputedStyle(el).outlineStyle);

test("naviguer a la souris ne dessine pas d'anneau autour du titre", async ({ page }) => {
  await ouvrirParametres(page);

  const titre = page.locator("#page-parametres .page-title");
  await expect(titre).toBeFocused();
  await expect(titre).toHaveClass(/focus-discret/);
  expect(await anneau(titre)).toBe("none");
});

test("naviguer au clavier laisse l'anneau au titre", async ({ page, browserName }) => {
  await ouvrirParametres(page);

  const nav = page.locator('.nav-item[data-page="librairie"]');
  await nav.focus();
  await page.keyboard.press("Enter");

  const titre = page.locator("#page-librairie .page-title");
  await expect(titre).toBeFocused();
  await expect(titre).not.toHaveClass(/focus-discret/);

  if (browserName === "chromium") expect(await anneau(titre)).not.toBe("none");
});

test("la regle :focus-visible globale reste en place", async ({ page }) => {
  await ouvrirParametres(page);

  const regle = await page.evaluate(() => {
    for (const feuille of document.styleSheets) {
      let regles;
      try { regles = feuille.cssRules; } catch { continue; }
      for (const r of regles) {
        if (r.selectorText?.includes("[tabindex]:focus-visible")
            && r.style?.outline) return true;
      }
    }
    return false;
  });
  expect(regle).toBe(true);
});

// La vraie reproduction : la fiche s'ouvre depuis une carte — un <div>, que le
// clic ne focalise pas — donc le focus a rendre est reste sur le titre de la
// page. Le rendre apres un Echap y dessinait le rectangle bleu.
test("fermer une modale au clavier ne dessine pas d'anneau sur le titre", async ({ page }) => {
  await ouvrirParametres(page);
  const titre = page.locator("#page-parametres .page-title");

  await page.evaluate(() => {
    document.querySelector(".page-title").focus();
    document.getElementById("modal-login").classList.remove("hidden");
  });
  await page.waitForTimeout(150);

  await page.keyboard.press("Escape");
  await expect(titre).toBeFocused();
  expect(await anneau(titre)).toBe("none");
});

// Contre-epreuve : un bouton, lui, reste tabulable et garde son anneau.
test("le focus rendu a un bouton garde son anneau", async ({ page, browserName }) => {
  await ouvrirParametres(page);

  await page.evaluate(() => {
    document.getElementById("settings-save").focus();
    document.getElementById("modal-login").classList.remove("hidden");
  });
  await page.waitForTimeout(150);
  await page.keyboard.press("Escape");

  const bouton = page.locator("#settings-save");
  await expect(bouton).toBeFocused();
  await expect(bouton).not.toHaveClass(/focus-discret/);
  if (browserName === "chromium") expect(await anneau(bouton)).not.toBe("none");
});

// --- 2. placeholder ampute ---------------------------------------------------

for (const champ of ["set-dldir", "set-scandir"]) {
  test(`le placeholder de #${champ} tient dans le champ`, async ({ page }) => {
    await ouvrirParametres(page);

    const trop_long = await page.locator(`#${champ}`).evaluate((el) => {
      const sonde = document.createElement("span");
      const style = getComputedStyle(el);
      sonde.textContent = el.placeholder;
      sonde.style.cssText =
        `position:absolute;visibility:hidden;white-space:pre;font:${style.font}`;
      document.body.appendChild(sonde);
      const largeurTexte = sonde.getBoundingClientRect().width;
      sonde.remove();
      const dispo = el.clientWidth
        - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return largeurTexte > dispo;
    });
    expect(trop_long).toBe(false);
  });
}

// --- 3. pastille de valeur contre pouce du curseur ---------------------------

test("la pastille de valeur ne chevauche pas le pouce du curseur", async ({ page }) => {
  await ouvrirParametres(page);

  const chevauche = await page.evaluate(() => {
    const pastille = document.getElementById("thread-val").getBoundingClientRect();
    const curseur = document.getElementById("set-threads").getBoundingClientRect();
    // Le pouce est centre sur la piste : il monte de la moitie de sa hauteur
    // au-dessus du milieu du champ, quelle que soit sa position horizontale.
    const hautDuPouce = curseur.top + curseur.height / 2 - 9;
    return pastille.bottom > hautDuPouce;
  });
  expect(chevauche).toBe(false);
});

test("le curseur reserve la hauteur de son pouce", async ({ page }) => {
  await ouvrirParametres(page);

  const h = await page.locator("#set-threads")
    .evaluate((el) => el.getBoundingClientRect().height);
  expect(h).toBeGreaterThanOrEqual(18);
});

// --- 4. deux lignes d'aide redondantes ---------------------------------------

test("un seul message d'aide par champ de dossier", async ({ page }) => {
  await ouvrirParametres(page);

  await expect(page.locator("#set-dldir-reel")).toHaveCount(0);
  await expect(page.locator("#set-scandir-reel")).toHaveCount(0);
  // Le verdict arrive apres un aller-retour : sans cette attente on compterait
  // une ligne encore vide.
  await expect(page.locator("#set-dldir-verdict")).not.toBeEmpty();

  const lignes = await page.$$eval(
    "#page-parametres .form-group:has(#set-dldir) .set-help",
    (els) => els.map((e) => e.textContent.trim()).filter(Boolean),
  );
  expect(lignes).toHaveLength(1);
});

test("champ vide : la ligne dit ou vont vraiment les fichiers", async ({ page }) => {
  await ouvrirParametres(page);

  const attendu = await page.evaluate(async () => {
    const s = await fetch("/api/health").then((r) => r.json());
    return s.disk.downloads.path;
  });
  await expect(page.locator("#set-dldir-verdict")).toHaveText(`Dossier par défaut : ${attendu}`);
});

test("chemin joignable : le chemin resolu n'est pas repete", async ({ page, request }) => {
  const sante = await (await request.get("/api/health")).json();
  const reel = sante.disk.downloads.path;

  await ouvrirParametres(page, { ...REGLAGES, downloads_dir: reel });

  const verdict = page.locator("#set-dldir-verdict");
  await expect(verdict).toContainText("Dossier existant");

  const texte = await verdict.textContent();
  expect(texte).not.toContain("à la place");
  // Le chemin apparait une fois, pas deux.
  expect(texte.split(reel).length - 1).toBe(1);
});

test("chemin injoignable : le repli est annonce sur la meme ligne", async ({ page }) => {
  const injoignable = "Z:\\partage\\eteint\\anime";
  await ouvrirParametres(page, { ...REGLAGES, downloads_dir: injoignable });

  const verdict = page.locator("#set-dldir-verdict");
  await expect(verdict).toHaveClass(/set-verdict-ko/);
  await expect(verdict).toContainText("les fichiers vont dans");
  await expect(verdict).toContainText("à la place");
});

// --- 5. largeur de la page ---------------------------------------------------

test("jamais plus de deux colonnes, meme sur un tres grand ecran", async ({ page }) => {
  await page.setViewportSize({ width: 2294, height: 1000 });
  await ouvrirParametres(page);

  const colonnes = await page.locator("#settings-form")
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
  expect(colonnes).toBeLessThanOrEqual(2);
});

test("la page est plafonnee en largeur et centree", async ({ page }) => {
  await page.setViewportSize({ width: 2294, height: 1000 });
  await ouvrirParametres(page);

  const form = await page.locator("#settings-form").boundingBox();
  const main = await page.locator(".main").boundingBox();
  expect(form.width).toBeLessThanOrEqual(960);

  const margeGauche = form.x - main.x;
  const margeDroite = main.x + main.width - (form.x + form.width);
  expect(Math.abs(margeGauche - margeDroite)).toBeLessThan(60);
});

test("les cartes d'une meme rangee ont la meme hauteur", async ({ page }) => {
  await page.setViewportSize({ width: 1400, height: 1000 });
  await ouvrirParametres(page);

  const hauteurs = await page.$$eval("#settings-form .set-groupe", (els) =>
    els.map((e) => {
      const r = e.getBoundingClientRect();
      return [Math.round(r.top), Math.round(r.height)];
    }));

  const parRangee = new Map();
  for (const [haut, hauteur] of hauteurs) {
    if (!parRangee.has(haut)) parRangee.set(haut, []);
    parRangee.get(haut).push(hauteur);
  }
  expect(parRangee.size).toBeGreaterThan(0);
  for (const groupe of parRangee.values()) {
    expect(Math.max(...groupe) - Math.min(...groupe)).toBeLessThanOrEqual(1);
  }
});

test("le bloc compte suit la meme largeur que le formulaire", async ({ page }) => {
  await page.setViewportSize({ width: 2294, height: 1000 });
  await ouvrirParametres(page);

  const form = await page.locator("#settings-form").boundingBox();
  const compte = await page.locator(".set-compte").boundingBox();
  expect(Math.abs(compte.width - form.width)).toBeLessThan(2);
  expect(Math.abs(compte.x - form.x)).toBeLessThan(2);
});
