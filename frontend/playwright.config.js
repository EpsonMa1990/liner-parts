import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 60000,
  outputDir: '../artifacts/playwright',
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:17654', viewport: { width: 1480, height: 940 }, trace: 'retain-on-failure', channel: process.env.LINER_TEST_BROWSER || undefined },
  webServer: {
    command: process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe ../tests/e2e_server.py' : '../.venv/bin/python ../tests/e2e_server.py',
    url: 'http://127.0.0.1:17654/session?token=e2e-local-token',
    timeout: 30000,
    reuseExistingServer: false,
  },
})
