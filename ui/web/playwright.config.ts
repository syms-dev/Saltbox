import { defineConfig, devices } from '@playwright/test';

const PORT = 8790;
export const E2E_TOKEN = 'e2e-token';

/**
 * End-to-end tests: the real daemon (routes, token check, job runner) serving the built web app,
 * on a throwaway box with fake sb, docker and registry (ui/tests/e2e_box.py). Build the web app first.
 * Traefik adds the bearer token in production; here the browser sends it.
 */
export default defineConfig({
  forbidOnly: !!process.env['CI'],
  fullyParallel: false,
  projects: [
    { name: 'desktop', testMatch: /functional\.spec\.ts/, use: { ...devices['Desktop Chrome'] } },
    {
      name: 'tablet',
      testMatch: /layout\.spec\.ts/,
      use: { ...devices['iPad Pro 11 landscape'], browserName: 'chromium', colorScheme: 'dark' },
    },
    { name: 'phone', testMatch: /layout\.spec\.ts/, use: { ...devices['Pixel 7'] } },
  ],
  reporter: process.env['CI'] ? 'github' : 'list',
  retries: 0,
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    extraHTTPHeaders: { Authorization: `Bearer ${E2E_TOKEN}` },
    trace: 'off',
  },
  webServer: {
    command: `.venv/bin/python -m tests.e2e_box --port ${PORT} --token ${E2E_TOKEN}`,
    cwd: '..',
    reuseExistingServer: false,
    stdout: 'ignore',
    timeout: 60_000,
    url: `http://127.0.0.1:${PORT}/api/meta`,
  },
  workers: 1,
});
