const { test, expect } = require("@playwright/test");
const { openMap, pickPlace } = require("./page");

test("the map opens and a district can be picked", async ({ page }) => {
  await openMap(page);
  await pickPlace(page, "Khulna");
  await expect(page.locator("#place h2")).toContainText("Khulna");
});
