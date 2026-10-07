const { expect } = require("@playwright/test");

// /map builds today's page from the live sources on first request, so the first test waits for it.
async function openMap(page, { lang = "en", theme = "light" } = {}) {
  await page.addInitScript(([l, t]) => { localStorage.setItem("dl-lang", l); localStorage.setItem("dl-theme", t); }, [lang, theme]);
  await page.goto("/map", { timeout: 240_000 });
  await expect(page.locator("#legend")).toBeVisible();
}

async function pickPlace(page, name) {
  await page.locator("#search").fill(name);
  await page.locator("#search-results [role=option]").first().click();
  await expect(page.locator("#place")).toBeVisible();
}

module.exports = { openMap, pickPlace };
