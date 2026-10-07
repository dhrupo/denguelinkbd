const { test, expect } = require("@playwright/test");
const { openMap, pickPlace } = require("./page");

test("the place panel gives a likely range around next week's number", async ({ page }) => {
  await openMap(page);
  await pickPlace(page, "Khulna");
  await expect(page.locator("#place-body")).toContainText(/Likely between [\d,]+ and [\d,]+\./);
});

test("the range reads in Bangla too", async ({ page }) => {
  await openMap(page, { lang: "bn" });
  await pickPlace(page, "খুলনা");
  await expect(page.locator("#place-body")).toContainText(/সম্ভবত [০-৯,]+ থেকে [০-৯,]+ জনের মধ্যে।/);
});
