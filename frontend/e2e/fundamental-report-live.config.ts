import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig } from '@playwright/test';

export default defineConfig({
    testDir: '.',
    testMatch: ['fundamental-report.live.spec.ts', 'fundamental-report-live.retained.spec.ts', 'fundamental-report-reading.live.spec.ts'],
    outputDir: process.env.FUNDAMENTAL_LIVE_OUTPUT_DIR ?? join(tmpdir(), 'fundamental-report-live'),
    fullyParallel: false,
    workers: 1,
    retries: 0,
    timeout: 360_000,
    expect: { timeout: 15_000 },
    reporter: 'list',
    use: {
        baseURL: process.env.FUNDAMENTAL_LIVE_BASE_URL,
        browserName: 'chromium',
        viewport: { width: 1440, height: 1000 },
        trace: 'off',
        video: 'off',
        screenshot: 'off',
    },
});
