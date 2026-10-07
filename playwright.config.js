const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8020", screenshot: "only-on-failure", timezoneId: "Asia/Dhaka", locale: "en-GB" },
  projects: [
    { name: "phone", use: { ...devices["Pixel 7"] } },
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
  ],
  webServer: {
    command: "uv run python -c \"from dengue_link.server import make_server; make_server(8020).serve_forever()\"",
    url: "http://127.0.0.1:8020/",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
