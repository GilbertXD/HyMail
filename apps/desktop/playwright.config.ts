import { defineConfig, devices } from "@playwright/test";

// Overridable so the suite can run next to a dev server that already holds
// the default ports. The API server reads the same variables.
const API_PORT = Number(process.env.HYMAIL_E2E_API_PORT ?? 8000);
const WEB_PORT = Number(process.env.HYMAIL_E2E_WEB_PORT ?? 5173);
const IMAP_PORT = Number(process.env.HYMAIL_E2E_IMAP_PORT ?? 11430);

const API_ORIGIN = `http://127.0.0.1:${API_PORT}`;
const WEB_ORIGIN = `http://127.0.0.1:${WEB_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  // Every spec shares one API server and one SQLite database, so files must
  // not race each other for the same rows.
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: WEB_ORIGIN,
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
      command: ".venv\\Scripts\\python.exe scripts\\run_e2e_server.py",
      cwd: "../api",
      url: `${API_ORIGIN}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        HYMAIL_E2E_API_PORT: String(API_PORT),
        HYMAIL_E2E_IMAP_PORT: String(IMAP_PORT),
        HYMAIL_E2E_WEB_PORT: String(WEB_PORT),
      },
    },
    {
      command: `pnpm dev --host 127.0.0.1 --port ${WEB_PORT}`,
      cwd: ".",
      url: WEB_ORIGIN,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        // Without this the app would still call the default API port.
        VITE_API_BASE_URL: API_ORIGIN,
      },
    },
  ],
});
