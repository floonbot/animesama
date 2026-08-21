import { expect, test } from "@playwright/test";

test("app shell renders (sidebar + nav)", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#app")).toBeVisible();
  await expect(page.locator(".sidebar")).toBeVisible();
  await expect(page.locator(".nav-item").first()).toBeVisible();
});

test("health endpoint is OK", async ({ request }) => {
  const res = await request.get("/api/health");
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.version).toBeTruthy();
});

test("a11y: skip-link is the first focusable element", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.locator(".skip-link")).toBeFocused();
});

test("keyboard: nav items are reachable and activate a page", async ({ page }) => {
  await page.goto("/");
  const fav = page.locator('.nav-item[data-page="favoris"]');
  await fav.focus();
  await page.keyboard.press("Enter");
  await expect(fav).toHaveAttribute("aria-current", "page");
});

test("toasts: a burst of error toasts does not freeze the UI", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#app")).toBeVisible();

  await page.evaluate(async () => {
    const { toast } = await import("/js/components/toast.js");
    for (let i = 0; i < 12; i++) toast("echec episode " + i, "error", 6000);
  });

  await expect(page.locator("#toasts .toast:not(.removing)")).toHaveCount(5);

  const fav = page.locator('.nav-item[data-page="favoris"]');
  await fav.focus();
  await page.keyboard.press("Enter");
  await expect(fav).toHaveAttribute("aria-current", "page");
});
