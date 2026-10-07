const { test, expect } = require("@playwright/test");
const { openMap, pickPlace } = require("./page");

const pageData = (page) => page.evaluate(() => JSON.parse(document.getElementById("data").textContent));

test("the place panel shows the coming weeks that passed the accuracy check, with a range for each", async ({ page }) => {
  await openMap(page);
  const ahead = (await pageData(page)).ahead;
  test.skip(!ahead, "No week beyond next week beat the simple guess in today's build");
  await pickPlace(page, "Khulna");
  const chart = page.locator("#place-body .ahead");
  await expect(chart).toBeVisible();
  await expect(chart.locator("h3")).toHaveText(`The next ${ahead.weeks.length + 1} weeks`);
  await expect(chart.locator("li")).toHaveCount(ahead.weeks.length + 1);
  await expect(chart.locator("li").first()).toHaveText(/^Week of \d+ \w+: about [\d,]+ \(likely [\d,]+–[\d,]+\)$/);
  await expect(chart.locator("svg .band")).toHaveCount(1);
  // Next week starts exactly 7 days before the first week further ahead, in Dhaka's calendar.
  const nextWeek = new Date(Date.parse(ahead.weeks[0] + "T00:00:00Z") - 7 * 864e5)
    .toLocaleDateString("en-GB", { day: "numeric", month: "long", timeZone: "UTC" });
  await expect(chart.locator("li").first()).toContainText(`Week of ${nextWeek}:`);
});

test("without weeks further ahead there is no chart", async ({ page }) => {
  let removed = false;
  await page.route("**/map", async (route) => {
    const res = await route.fetch();
    const body = await res.text();
    removed = body.includes('"ahead": {');
    await route.fulfill({ response: res, body: body.replace('"ahead": ', '"aheadGone": ') });
  });
  await openMap(page);
  await pickPlace(page, "Khulna");
  expect(removed).toBe(true);
  await expect(page.locator("#place-body .lead-big")).toBeVisible();
  await expect(page.locator("#place-body .ahead")).toHaveCount(0);
});

test("the coming weeks read in Bangla, with Bangla digits", async ({ page }) => {
  await openMap(page, { lang: "bn" });
  const ahead = (await pageData(page)).ahead;
  test.skip(!ahead, "No week beyond next week beat the simple guess in today's build");
  await pickPlace(page, "খুলনা");
  const weeks = String(ahead.weeks.length + 1).replace(/\d/g, (c) => "০১২৩৪৫৬৭৮৯"[c]);
  await expect(page.locator("#place-body .ahead h3")).toHaveText(`সামনের ${weeks} সপ্তাহ`);
  await expect(page.locator("#place-body .ahead p").first()).toContainText(`সামনের ${weeks} সপ্তাহে রোগী`);
});
