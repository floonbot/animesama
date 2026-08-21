import { expect, test } from "@playwright/test";

// Depuis que Parametres est une page (C13), la carte « Compte anime-sama » etait
// vide : _updateSettingsSection ecrivait style.display alors que les deux blocs
// portent la classe .hidden, qui est en display:none !important. Ni le bouton
// « Se connecter » ni « Deconnexion » n'apparaissaient jamais.

const REGLAGES = {
  qualite: "auto", thread_count: 16, downloads_dir: "", scans_dir: "",
  notifications: true, son_notif: true, confirm_suppr: true,
  skip_existants: true, langue_defaut: "VOSTFR",
};

async function ouvrir(page, auth) {
  await page.route("**/api/settings", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: REGLAGES });
    return r.fulfill({ json: { ok: true, settings: REGLAGES } });
  });
  await page.route("**/api/auth/status", (r) => r.fulfill({ json: auth }));
  await page.goto("/");
  await page.click("#nav-settings");
  await expect(page.locator("#page-parametres")).toHaveClass(/active/);
}

test("deconnecte : le bouton de connexion est visible", async ({ page }) => {
  await ouvrir(page, { connected: false });

  await expect(page.locator("#settings-login-section")).toBeVisible();
  await expect(page.locator("#settings-connect")).toBeVisible();
  await expect(page.locator("#settings-user-section")).toBeHidden();
});

test("connecte : le pseudo et la deconnexion sont visibles", async ({ page }) => {
  await ouvrir(page, { connected: true, username: "utilisateur_test" });

  await expect(page.locator("#settings-user-section")).toBeVisible();
  await expect(page.locator("#settings-username")).toHaveText("utilisateur_test");
  await expect(page.locator("#settings-logout")).toBeVisible();
  await expect(page.locator("#settings-login-section")).toBeHidden();
});

test("le bouton de connexion ouvre bien la modale", async ({ page }) => {
  await ouvrir(page, { connected: false });

  await page.click("#settings-connect");
  await expect(page.locator("#modal-login")).not.toHaveClass(/hidden/);
});

test("la carte compte n'est jamais une boite vide", async ({ page }) => {
  await ouvrir(page, { connected: false });

  const boutons = await page.locator(".set-compte button:visible").count();
  expect(boutons).toBeGreaterThan(1);
});
