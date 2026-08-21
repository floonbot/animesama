import { expect, test } from "@playwright/test";

// C13.a — Parametres devient une page routee comme les autres, dit ou vont
// vraiment les fichiers, et ne fabrique plus de dossier fantome sur une faute
// de frappe.

const REGLAGES = {
  qualite: "720",
  thread_count: 8,
  downloads_dir: "",
  scans_dir: "",
  notifications: true,
  son_notif: false,
  confirm_suppr: true,
  skip_existants: true,
  langue_defaut: "VF",
};

async function ouvrirParametres(page) {
  await page.route("**/api/settings", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: REGLAGES });
    return r.fulfill({ json: { ok: true, settings: REGLAGES } });
  });
  await page.goto("/");
  await page.click("#nav-settings");
  await expect(page.locator("#page-parametres")).toHaveClass(/active/);
}

test("Parametres est une page, pas une modale", async ({ page }) => {
  await ouvrirParametres(page);

  await expect(page.locator("#modal-settings")).toHaveCount(0);
  await expect(page.locator('#nav-settings')).toHaveClass(/active/);
  await expect(page.locator('#nav-settings')).toHaveAttribute("aria-current", "page");
});

test("les fleches arriere/avant traversent Parametres", async ({ page }) => {
  await ouvrirParametres(page);

  await page.click('.nav-item[data-page="librairie"]');
  await expect(page.locator("#page-librairie")).toHaveClass(/active/);

  await page.click("#nav-back");
  await expect(page.locator("#page-parametres")).toHaveClass(/active/);

  await page.click("#nav-forward");
  await expect(page.locator("#page-librairie")).toHaveClass(/active/);
});

test("les neuf reglages sont groupes en sections", async ({ page }) => {
  await ouvrirParametres(page);

  // L'emoji vit dans son propre span aria-hidden : on compare l'intitulé seul,
  // pas la concaténation du décor et du texte.
  const legendes = await page.$$eval("#page-parametres .set-groupe .set-legende",
    (els) => els.map((e) => {
      const c = e.cloneNode(true);
      c.querySelector(".set-legende-icone")?.remove();
      return c.textContent.trim();
    }));
  expect(legendes).toEqual([
    "Téléchargement", "Dossiers", "Notifications",
    "Comportement", "Compte anime-sama",
  ]);

  for (const id of ["set-qualite", "set-threads", "set-dldir", "set-scandir",
    "set-notifs", "set-son", "set-skip", "set-confirm", "set-langue"]) {
    await expect(page.locator(`#${id}`)).toHaveCount(1);
  }
});

test("les valeurs enregistrees sont rejouees dans le formulaire", async ({ page }) => {
  await ouvrirParametres(page);

  await expect(page.locator("#set-qualite")).toHaveValue("720");
  await expect(page.locator("#set-threads")).toHaveValue("8");
  await expect(page.locator("#thread-val")).toHaveText("8");
  await expect(page.locator("#set-langue")).toHaveValue("VF");
  await expect(page.locator("#set-son")).not.toBeChecked();
  await expect(page.locator("#set-skip")).toBeChecked();
});

// Le chemin resolu a fusionne avec le verdict : sur un champ vide c'est lui
// qui dit ou les fichiers atterrissent.
test("le chemin reellement utilise est affiche", async ({ page, request }) => {
  await ouvrirParametres(page);
  const sante = await (await request.get("/api/health")).json();

  await expect(page.locator("#set-dldir-verdict"))
    .toContainText(sante.disk.downloads.path);
  await expect(page.locator("#set-scandir-verdict"))
    .toContainText(sante.disk.scans.path);
});

test("un dossier invalide est signale avant l'enregistrement", async ({ page }) => {
  await ouvrirParametres(page);
  let poste = false;
  await page.route("**/api/settings", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: REGLAGES });
    poste = true;
    return r.fulfill({ json: { ok: true, settings: REGLAGES } });
  });

  await page.fill("#set-dldir", "Z:/vraiment/pas/la");
  await expect(page.locator("#set-dldir-verdict")).toHaveClass(/set-verdict-ko/);

  await page.click("#settings-save");
  await expect(page.locator("#settings-error")).not.toHaveClass(/hidden/);
  expect(poste).toBe(false);
});

test("creer un dossier absent demande confirmation", async ({ page }) => {
  await ouvrirParametres(page);
  let poste = false;
  await page.route("**/api/settings", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: REGLAGES });
    poste = true;
    return r.fulfill({ json: { ok: true, settings: REGLAGES } });
  });

  const cible = await page.evaluate(async () => {
    const s = await fetch("/api/health").then((r) => r.json());
    return s.disk.temp.path + "/animesama-e2e-nouveau";
  });

  await page.fill("#set-dldir", cible);
  await expect(page.locator("#set-dldir-verdict")).toHaveClass(/set-verdict-avertit/);

  page.once("dialog", (d) => d.dismiss());
  await page.click("#settings-save");
  await page.waitForTimeout(300);
  expect(poste).toBe(false);

  page.once("dialog", (d) => d.accept());
  await page.click("#settings-save");
  await expect.poll(() => poste).toBe(true);
});

test("sans pont natif, le champ texte reste et aucun bouton Parcourir n'apparait", async ({ page }) => {
  await ouvrirParametres(page);

  expect(await page.evaluate(() => !!window.pywebview)).toBe(false);
  await expect(page.locator("#set-dldir-parcourir")).toBeHidden();
  await expect(page.locator("#set-dldir")).toBeEditable();
});

test("le lien vers le diagnostic marche depuis la page", async ({ page }) => {
  await ouvrirParametres(page);

  await page.click("#settings-diag");
  await expect(page.locator("#page-diag")).toHaveClass(/active/);
});
