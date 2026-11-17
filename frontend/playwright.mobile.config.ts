import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'mobile.spec.ts',
  workers: 1,
  timeout: 30000,
  use: {baseURL: 'http://127.0.0.1:22393', headless: true, locale: 'zh-CN', viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true},
  webServer: {
    command: '".venv\\Scripts\\python.exe" -m tests.serve_mobile_frontend',
    cwd: '..',
    url: 'http://127.0.0.1:22393/health',
    timeout: 30000,
    reuseExistingServer: false,
  },
})
