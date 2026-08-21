import { expect, test } from "@playwright/test";

// C13.0 — relire ce qu'on tape, sans casser ce dont les gestionnaires de mots
// de passe dependent : `autocomplete`, l'identite du noeud, la touche Entree.

async function ouvrirConnexion(page) {
  await page.route("**/api/auth/status", (r) =>
    r.fulfill({ json: { connected: false, username: null } }));
  await page.goto("/");
  await page.click("#hero-connect");
  await expect(page.locator("#modal-login")).not.toHaveClass(/hidden/);
}

const champ = (page) => page.locator("#login-password");
const bascule = (page) => page.locator("#login-password-voir");

test("masque par defaut, revele au clic, remasque au second clic", async ({ page }) => {
  await ouvrirConnexion(page);

  await expect(champ(page)).toHaveAttribute("type", "password");
  await expect(bascule(page)).toHaveAttribute("aria-pressed", "false");

  await bascule(page).click();
  await expect(champ(page)).toHaveAttribute("type", "text");
  await expect(bascule(page)).toHaveAttribute("aria-pressed", "true");

  await bascule(page).click();
  await expect(champ(page)).toHaveAttribute("type", "password");
  await expect(bascule(page)).toHaveAttribute("aria-pressed", "false");
});

test("l'etiquette accessible dit ce que le bouton va faire", async ({ page }) => {
  await ouvrirConnexion(page);

  await expect(bascule(page)).toHaveAttribute("aria-label", "Afficher le mot de passe");
  await bascule(page).click();
  await expect(bascule(page)).toHaveAttribute("aria-label", "Masquer le mot de passe");
});

test("la saisie survit a la bascule, et autocomplete reste intact", async ({ page }) => {
  await ouvrirConnexion(page);

  await champ(page).fill("s3cr3t-é");
  await bascule(page).click();
  await expect(champ(page)).toHaveValue("s3cr3t-é");
  await expect(champ(page)).toHaveAttribute("autocomplete", "current-password");

  await champ(page).type("X");
  await expect(champ(page)).toHaveValue("s3cr3t-éX");
});

test("Entree soumet toujours depuis le champ revele", async ({ page }) => {
  await ouvrirConnexion(page);
  let poste = false;
  await page.route("**/api/auth/login", (r) => {
    poste = true;
    return r.fulfill({ json: { ok: false, message: "Identifiants incorrects" } });
  });

  await page.fill("#login-pseudo", "moi");
  await champ(page).fill("motdepasse");
  await bascule(page).click();
  await champ(page).press("Enter");

  await expect(page.locator("#login-error")).not.toHaveClass(/hidden/);
  expect(poste).toBe(true);
});

test("rien n'est memorise : fermer puis rouvrir remasque et vide", async ({ page }) => {
  await ouvrirConnexion(page);

  await champ(page).fill("motdepasse");
  await bascule(page).click();
  await expect(champ(page)).toHaveAttribute("type", "text");

  await page.click("#login-cancel");
  await page.click("#hero-connect");

  await expect(champ(page)).toHaveAttribute("type", "password");
  await expect(champ(page)).toHaveValue("");
});

test("Echap ne laisse pas le mot de passe en clair", async ({ page }) => {
  await ouvrirConnexion(page);

  await champ(page).fill("motdepasse");
  await bascule(page).click();
  await page.keyboard.press("Escape");
  await expect(page.locator("#modal-login")).toHaveClass(/hidden/);

  await page.click("#hero-connect");
  await expect(champ(page)).toHaveAttribute("type", "password");
  await expect(champ(page)).toHaveValue("");
});

test("le bouton est atteignable au clavier", async ({ page }) => {
  await ouvrirConnexion(page);

  await champ(page).focus();
  await page.keyboard.press("Tab");
  await expect(bascule(page)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(champ(page)).toHaveAttribute("type", "text");
});
