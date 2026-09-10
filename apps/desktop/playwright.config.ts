import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8000;
const WEB_PORT = 5173;
const IMAP_PORT = 11430;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    channel: "msedge",
  },
  projects: [
    {
      name: "edge",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "uv run python scripts/run_e2e_server.py",
      cwd: "../api",
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        HYMAIL_E2E_API_PORT: String(API_PORT),
        HYMAIL_E2E_IMAP_PORT: String(IMAP_PORT),
      },
    },
    {
      command: `pnpm dev --host 127.0.0.1 --port ${WEB_PORT}`,
      cwd: ".",
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});