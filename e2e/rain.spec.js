const { test, expect } = require("@playwright/test");
const { openMap, pickPlace } = require("./page");

const RAIN = /Met Department forecast for \d+ \w+–\d+ \w+: (about [\d,]+ mm of rain|no rain expected) in Khulna district\./;

test("the place panel gives the Met Department's rain forecast for the district", async ({ page }) => {
  await openMap(page);
  await pickPlace(page, "Khulna");
  await expect(page.locator("#place-body")).toContainText(RAIN);
});

test("the district rain reads in Bangla", async ({ page }) => {
  await openMap(page, { lang: "bn" });
  await pickPlace(page, "খুলনা");
  await expect(page.locator("#place-body")).toContainText(/আবহাওয়া অধিদপ্তরের পূর্বাভাস \([^)]+\): খুলনা জেলায় (প্রায় [০-৯,]+ মিলিমিটার বৃষ্টি হতে পারে|বৃষ্টির সম্ভাবনা নেই)/);
});

test("without the district forecast the line is simply left out", async ({ page }) => {
  let removed = false;
  await page.route("**/map", async (route) => {
    const res = await route.fetch();
    const body = await res.text();
    removed = body.includes('"rainWeek": {');
    await route.fulfill({ response: res, body: body.replace('"rainWeek": ', '"rainWeekGone": ') });
  });
  await openMap(page);
  await pickPlace(page, "Khulna");
  await expect(page.locator("#place-body")).toContainText("Khulna");
  expect(removed).toBe(true);
  await expect(page.locator("#place-body")).not.toContainText("Met Department forecast for");
});

const day = (n) => new Date(Date.now() + 6 * 3600e3 + n * 864e5).toISOString().slice(0, 10);

async function homeWithForecast(page, khulnaMm) {
  await page.route("**/map", async (route) => {
    const res = await route.fetch();
    const body = (await res.text()).replace(/"rainWeek": \{"from": "[^"]*", "to": "[^"]*", "districts": \{[^}]*\}\}/,
      `"rainWeek": {"from": "${day(0)}", "to": "${day(3)}", "districts": {"Khulna": ${khulnaMm}}}`);
    await route.fulfill({ response: res, body });
  });
  await page.addInitScript((on) => {
    localStorage.setItem("dl-place", "Khulna");
    localStorage.setItem("dl-home", JSON.stringify({ on, done: ["pots", "buckets"] }));
  }, day(-1));
  await openMap(page);
}

test("with only light rain coming, yesterday's home checklist stays ticked", async ({ page }) => {
  await homeWithForecast(page, 5.0);
  await page.goto("/map#help");
  await expect(page.locator("#home-check input:checked")).toHaveCount(2);
  await expect(page.locator("#home-rain")).toBeHidden();
});

test("rain forecast for your district clears last week's home checklist and says why", async ({ page }) => {
  await homeWithForecast(page, 25.0);
  await page.goto("/map#help");
  await expect(page.locator("#home-rain")).toHaveText("The Met Department expects rain in Khulna district in the coming days. Check these again once it stops.");
  await expect(page.locator("#home-check input:checked")).toHaveCount(0);
});
