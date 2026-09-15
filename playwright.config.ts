import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "browser-tests",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:8878",
    browserName: "chromium",
    channel: "msedge",
    headless: true,
    trace: "retain-on-failure",
  },
});
