import { defineConfig } from '@playwright/test';

const baseURL = 'http://127.0.0.1:43192';

export default defineConfig({
    testDir: './e2e',
    outputDir: '/tmp/value-investment-agent-issue-192-playwright',
    fullyParallel: false,
    workers: 1,
    timeout: 30_000,
    expect: { timeout: 10_000 },
    reporter: 'list',
    use: {
        baseURL,
        browserName: 'chromium',
        trace: 'retain-on-failure',
    },
    webServer: {
        command: 'npm run dev -- --hostname 127.0.0.1 --port 43192',
        url: `${baseURL}/login`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
    },
});
