import { defineConfig } from "@playwright/test";

/**
 * E2E tests run against a fully started stack (docker compose up, or a local
 * backend + built frontend). Base URL and admin token come from the
 * environment; see .github/workflows/e2e.yml.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 40_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8000",
    trace: "retain-on-failure",
  },
});
