const { test, expect } = require("@playwright/test");
const { openMap } = require("./page");

test("get help lists Dhaka North's dengue control room as tap-to-call numbers", async ({ page }) => {
  await openMap(page);
  await page.goto("/map#help");
  const card = page.locator("#view-help .card", { hasText: "Dhaka North" });
  await expect(card).toBeVisible();
  for (const n of ["01716063425", "01773393276", "01715238754"]) await expect(card.locator(`a[href="tel:${n}"]`)).toBeVisible();
});
