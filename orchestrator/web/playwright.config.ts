import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5182',
    viewport: { width: 1280, height: 900 },
    launchOptions: process.env.CLADE_BROWSER_PATH ? { executablePath: process.env.CLADE_BROWSER_PATH } : {},
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5182 --strictPort',
    url: 'http://127.0.0.1:5182/web/',
    reuseExistingServer: false,
  },
});
