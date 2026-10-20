import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
export default defineConfig({
  testDir: "./tests",
  timeout: process.env.STUDIO_URL ? 900000 : 120000,
  workers: 1,
  retries: 0,
  use: {
    actionTimeout: 30000,
    navigationTimeout: 60000,
    baseURL: process.env.STUDIO_URL || "http://127.0.0.1:3000",
    headless: true,
    launchOptions: {
      executablePath:
        process.env.CHROMIUM_PATH ||
        (existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined),
      args: ["--no-sandbox"],
    },
    screenshot: "only-on-failure",
    trace: process.env.STUDIO_EMAIL ? "off" : "retain-on-failure",
  },
  reporter: [["list"], ["html", { open: "never" }]],
});
