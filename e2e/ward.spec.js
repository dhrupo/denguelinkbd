const { test, expect } = require("@playwright/test");
const { openMap } = require("./page");

async function searchWard(page, name) {
  await page.locator("#search").fill(name);
  const option = page.locator("#search-results [role=option]", { hasText: name }).first();
  await expect(option).toContainText(/Ward 15|১৫ নম্বর ওয়ার্ড/);
  await option.click();
  const popup = page.locator(".leaflet-popup-content");
  await expect(popup).toBeVisible();
  // The popup must not open underneath the cards that float over the map.
  await expect.poll(() => popup.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return [[r.left + 8, r.top + 8], [r.right - 8, r.top + 8], [r.left + r.width / 2, r.bottom - 8]]
      .every(([x, y]) => el.closest(".leaflet-popup").contains(document.elementFromPoint(x, y)));
  })).toBe(true);
  return popup;
}

test("a neighbourhood search opens its Dhaka North ward with this week's patients", async ({ page }) => {
  await openMap(page);
  const popup = await searchWard(page, "Matikata");
  await expect(popup).toContainText(/Ward 15/);
  await expect(popup).toContainText(/[\d,]+ patients in the last 7 days/);
  await expect(popup).toContainText(/for every 100,000 people/);
  await expect(popup).toContainText(/how many patients there are \((low|moderate|high)\)/);
  // Screen-reader and keyboard users land in the popup, not back in the search box.
  await expect(popup).toBeFocused();
});

test("the ward popup reads in Bangla", async ({ page }) => {
  await openMap(page, { lang: "bn" });
  const popup = await searchWard(page, "Matikata");
  await expect(popup).toContainText(/গত ৭ দিনে রোগী [০-৯,]+ জন/);
});
