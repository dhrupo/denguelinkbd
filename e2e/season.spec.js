const { test, expect } = require("@playwright/test");
const { openMap } = require("./page");

test("hotspots compares this year with past years", async ({ page }) => {
  await openMap(page);
  await page.goto("/map#risk");
  const season = page.locator("#season");
  await expect(season).toBeVisible();
  await expect(season).toContainText(/In the last \d years, dengue peaked/);
  await expect(season.locator("svg polyline.now")).toHaveCount(1);
  await season.locator("summary").click();
  await expect(season.locator("tbody tr")).toHaveCount(12);
});

test("the comparison reads in Bangla", async ({ page }) => {
  await openMap(page, { lang: "bn" });
  await page.goto("/map#risk");
  await expect(page.locator("#season")).toContainText(/গত [০-৯] বছরে ডেঙ্গু সবচেয়ে বেশি ছড়িয়েছে/);
});
