const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { openMap, pickPlace } = require("./page");

for (const lang of ["en", "bn"]) for (const theme of ["light", "dark"]) {
  test(`no accessibility violations on any view (${lang}, ${theme})`, async ({ page }) => {
    await openMap(page, { lang, theme });
    await pickPlace(page, lang === "en" ? "Khulna" : "খুলনা");
    for (const view of ["map", "risk", "control", "help", "about"]) {
      await page.goto(`/map#${view}`);
      if (view === "risk") await page.locator("#season summary").click();
      const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(violations.map((v) => `${view}: ${v.id} (${v.nodes.length})`)).toEqual([]);
    }
  });
}
