import { expect, test } from "@playwright/test";

// settings.js:_verifier n'avait ni jeton de sequence ni garde de requete en vol.
// Un chemin UNC injoignable bloque une vingtaine de secondes cote serveur : si
// l'utilisateur corrige entre-temps par un chemin local qui repond en 5 ms, la
// reponse tardive ecrasait l'affichage par le verdict d'un chemin que le champ
// ne contient plus.

const REGLAGES = {
  qualite: "auto", thread_count: 16, downloads_dir: "", scans_dir: "",
  notifications: true, son_notif: true, confirm_suppr: true,
  skip_existants: true, langue_defaut: "VOSTFR",
};

const LENT = "\\\\SERVEUR_TEST\\eteinte\\anime";

// Le chemin lent repond apres le rapide, quel que soit l'ordre des clics.
async function sondeRetardee(page, { retardMs }) {
  await page.route("**/api/settings/verifier-dossier**", async (route) => {
    const chemin = new URL(route.request().url()).searchParams.get("chemin") || "";
    const lent = chemin.includes("SERVEUR_TEST");
    if (lent) await new Promise((r) => setTimeout(r, retardMs));
    await route.fulfill({
      json: lent
        ? { ok: false, defaut: false, existe: false, creable: false,
            chemin, message: `Emplacement introuvable ou non inscriptible : ${chemin}` }
        : { ok: true, defaut: false, existe: true, creable: false,
            inscriptible: true, chemin, message: `Dossier existant : ${chemin}` },
    });
  });
}

async function ouvrirParametres(page) {
  await page.route("**/api/settings", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: REGLAGES });
    return r.fulfill({ json: { ok: true, settings: REGLAGES } });
  });
  await page.goto("/");
  await page.click("#nav-settings");
  await expect(page.locator("#page-parametres")).toHaveClass(/active/);
}

test("la reponse tardive d'un chemin abandonne n'ecrase pas le verdict", async ({ page }) => {
  await sondeRetardee(page, { retardMs: 1500 });
  await ouvrirParametres(page);

  await page.fill("#set-dldir", LENT);
  await page.locator("#set-dldir").blur();

  // On corrige avant que la sonde lente ne reponde.
  await page.waitForTimeout(200);
  await page.fill("#set-dldir", "C:\\Temp");
  await page.locator("#set-dldir").blur();

  await expect(page.locator("#set-dldir-verdict")).toHaveClass(/set-verdict-ok/);

  // Le retard s'ecoule : rien ne doit bouger.
  await page.waitForTimeout(1800);
  await expect(page.locator("#set-dldir-verdict")).toHaveClass(/set-verdict-ok/);
  await expect(page.locator("#set-dldir-verdict")).toContainText("C:\\Temp");
  await expect(page.locator("#set-dldir-verdict")).not.toContainText("SERVEUR_TEST");
});

test("le verdict affiche correspond toujours au contenu du champ", async ({ page }) => {
  await sondeRetardee(page, { retardMs: 1200 });
  await ouvrirParametres(page);

  await page.fill("#set-dldir", LENT);
  await page.locator("#set-dldir").blur();
  await page.waitForTimeout(150);
  await page.fill("#set-dldir", "C:\\Temp");
  await page.locator("#set-dldir").blur();
  await page.waitForTimeout(1600);

  const champ = await page.inputValue("#set-dldir");
  const verdict = await page.locator("#set-dldir-verdict").textContent();
  expect(verdict).toContain(champ);
});

test("chaque champ de dossier garde son propre jeton", async ({ page }) => {
  await sondeRetardee(page, { retardMs: 800 });
  await ouvrirParametres(page);

  await page.fill("#set-dldir", LENT);
  await page.fill("#set-scandir", "C:\\Temp");
  await page.locator("#set-scandir").blur();
  await page.waitForTimeout(1400);

  await expect(page.locator("#set-scandir-verdict")).toHaveClass(/set-verdict-ok/);
  await expect(page.locator("#set-dldir-verdict")).toHaveClass(/set-verdict-ko/);
});

test("l'enregistrement decide sur le verdict qu'il vient d'obtenir", async ({ page }) => {
  await sondeRetardee(page, { retardMs: 300 });
  await ouvrirParametres(page);
  let poste = false;
  await page.route("**/api/settings", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: REGLAGES });
    poste = true;
    return r.fulfill({ json: { ok: true, settings: REGLAGES } });
  });

  await page.fill("#set-dldir", LENT);
  await page.click("#settings-save");

  await expect(page.locator("#settings-error")).not.toHaveClass(/hidden/);
  expect(poste).toBe(false);
});
