import { expect, test } from '@playwright/test';

const importPath = '/api/v1/llm/provider-keys/imports';

function syntheticKeys(batchNumber: number): string[] {
    return Array.from(
        { length: 100 },
        (_, index) => 'sk-or-v1-synthetic-' + batchNumber + '-' +
            String(index + 1).padStart(3, '0') + '-material',
    );
}

test('imports 100-key TXT and CSV files and shows safe per-key progress', async ({ page }) => {
    let batchNumber = 0;
    let expectedFormat: 'txt' | 'csv' = 'txt';
    const batches = new Map<string, number>();

    await page.route('**/api/v1/auth/me', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                auth_type: 'session',
                email: 'playwright@example.test',
                role: 'user',
                subject: 'playwright-user',
                user_id: 'playwright-user',
            }),
        });
    });
    await page.route('**/api/v1/llm/provider-keys**', async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.pathname === importPath + '/preview') {
            const contentType = request.headers()['content-type'] ?? '';
            expect(contentType).toContain('multipart/form-data;');
            expect(request.postDataBuffer()?.length ?? 0).toBeGreaterThan(0);
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    file_type: expectedFormat,
                    row_count: 100,
                    unique_count: 100,
                    duplicate_count: 0,
                    issues: [],
                }),
            });
            return;
        }

        if (url.pathname === importPath && request.method() === 'GET') {
            await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
            return;
        }

        if (url.pathname === importPath && request.method() === 'POST') {
            expect(request.headers()['content-type']).toContain('multipart/form-data;');
            expect(request.headers()['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/);
            batchNumber += 1;
            const batchId = 'batch-' + batchNumber;
            batches.set(batchId, batchNumber);
            await route.fulfill({
                status: 202,
                contentType: 'application/json',
                body: JSON.stringify(makeBatch(batchId, batchNumber, 'queued')),
            });
            return;
        }

        const batchId = url.pathname.split('/').at(-1);
        if (batchId && batches.has(batchId) && request.method() === 'GET') {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify(makeBatch(batchId, batches.get(batchId) ?? 0, 'completed')),
            });
            return;
        }

        if (url.pathname === '/api/v1/llm/provider-keys') {
            await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
            return;
        }

        await route.continue();
    });
    await page.route('**/api/v1/llm/settings', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                selected_model: 'openrouter/free',
                default_model: 'openrouter/free',
                models: [{
                    id: 'openrouter/free',
                    name: 'Free Models Router',
                    description: 'Selects a free model.',
                    context_length: null,
                }],
            }),
        });
    });

    await page.goto('/settings/llm');
    await expect(page.getByRole('heading', { name: 'Import provider keys' })).toBeVisible();

    const formatHelp = page.getByRole('button', { name: 'File format information' });
    for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
        await page.setViewportSize(viewport);
        await formatHelp.focus();
        await page.keyboard.press('Enter');
        const popover = page.getByRole('dialog');
        await expect(popover.getByRole('heading', { name: 'TXT format' })).toBeVisible();
        await expect(popover.getByRole('heading', { name: 'CSV format' })).toBeVisible();
        const bounds = await popover.boundingBox();
        expect(bounds).not.toBeNull();
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
        await page.keyboard.press('Escape');
    }

    for (const [number, format] of (['txt', 'csv'] as const).entries()) {
        expectedFormat = format;
        const keys = syntheticKeys(number + 1);
        const content = format === 'txt'
            ? keys.join('\n')
            : ['api_key,label', ...keys.map(
                (key, index) => key + ',Key ' + (index + 1),
            )].join('\n');
        await page.getByLabel('Key file').setInputFiles({
            name: 'keys.' + format,
            mimeType: format === 'txt' ? 'text/plain' : 'text/csv',
            buffer: Buffer.from(content),
        });
        await expect(page.getByText('100 rows · 100 unique keys · 0 duplicate rows')).toBeVisible();
        await expect(page.getByText(keys[0], { exact: true })).toHaveCount(0);
        await page.getByRole('button', { name: 'Import keys' }).click();
        await expect(page.getByText('The import was accepted. Its results will remain available here.')).toBeVisible();
        await expect(page.getByText('Completed').last()).toBeVisible({ timeout: 10_000 });
        await page.getByText('View per-key results').first().click();
        const latestBatch = page.locator('article').first();
        await expect(latestBatch.getByRole('cell', { name: 'Key 1', exact: true })).toBeVisible();
        await expect(latestBatch.getByRole('cell', { name: 'Key 100', exact: true })).toBeVisible();
        await expect(page.getByText('100 imported · 0 duplicates · 0 failed').last()).toBeVisible();
        await expect(page.getByText(keys[0], { exact: true })).toHaveCount(0);
    }
});

test('submits a manual key through durable import history', async ({ page }) => {
    const apiKey = 'sk-or-v1-manual-synthetic-key-00000001';
    let keyListReads = 0;

    await page.route('**/api/v1/auth/me', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                auth_type: 'session',
                email: 'playwright@example.test',
                role: 'user',
                subject: 'playwright-user',
                user_id: 'playwright-user',
            }),
        });
    });
    await page.route('**/api/v1/llm/provider-keys**', async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.pathname === '/api/v1/llm/provider-keys/imports' && request.method() === 'GET') {
            await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
            return;
        }
        if (url.pathname === '/api/v1/llm/provider-keys' && request.method() === 'POST') {
            expect(request.headers()['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/);
            expect(request.postDataJSON()).toEqual({ label: 'Manual research key', api_key: apiKey });
            await route.fulfill({
                status: 202,
                contentType: 'application/json',
                body: JSON.stringify(makeManualBatch('manual-batch-1', 'queued')),
            });
            return;
        }
        if (url.pathname === '/api/v1/llm/provider-keys/imports/manual-batch-1') {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify(makeManualBatch('manual-batch-1', 'completed')),
            });
            return;
        }
        if (url.pathname === '/api/v1/llm/provider-keys' && request.method() === 'GET') {
            keyListReads += 1;
            await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
            return;
        }
        await route.continue();
    });
    await page.route('**/api/v1/llm/settings', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                selected_model: 'openrouter/free',
                default_model: 'openrouter/free',
                models: [{
                    id: 'openrouter/free',
                    name: 'Free Models Router',
                    description: 'Selects a free model.',
                    context_length: null,
                }],
            }),
        });
    });

    await page.goto('/settings/llm');
    await page.getByLabel('Label').fill('Manual research key');
    await page.getByLabel('OpenRouter API key').fill(apiKey);
    await page.getByRole('button', { name: 'Add key' }).click();

    await expect(page.getByText('Queued')).toBeVisible();
    await expect(page.getByText('The key was submitted. Track its status in import history.')).toBeVisible();
    await expect(page.getByLabel('OpenRouter API key')).toHaveValue('');
    await expect(page.getByText('Completed')).toBeVisible({ timeout: 10_000 });
    await page.getByText('View per-key results').click();
    const importEntry = page.locator('article').first();
    await expect(importEntry.getByRole('cell', { name: 'Manual research key', exact: true })).toBeVisible();
    await expect(importEntry.getByRole('cell', { name: 'Imported', exact: true })).toBeVisible();
    await expect(page.getByText(apiKey, { exact: true })).toHaveCount(0);
    await expect.poll(() => keyListReads).toBeGreaterThan(1);
});

function makeBatch(
    id: string,
    batchNumber: number,
    status: 'queued' | 'completed',
) {
    const items = syntheticKeys(batchNumber).map((_, index) => ({
        source_line: index + 1,
        label: 'Key ' + (index + 1),
        suffix: String(index + 1).padStart(4, '0'),
        status: status === 'queued' ? 'queued' : 'imported',
        attempts: status === 'queued' ? 0 : 1,
        retryable: false,
    }));
    return {
        id,
        status,
        total_count: items.length,
        processed_count: status === 'queued' ? 0 : items.length,
        imported_count: status === 'queued' ? 0 : items.length,
        duplicate_count: 0,
        invalid_count: 0,
        retryable_count: 0,
        created_at: '2026-10-31T00:00:00Z',
        updated_at: '2026-10-31T00:00:00Z',
        items,
    };
}

function makeManualBatch(id: string, status: 'queued' | 'completed') {
    return {
        id,
        status,
        total_count: 1,
        processed_count: status === 'queued' ? 0 : 1,
        imported_count: status === 'queued' ? 0 : 1,
        duplicate_count: 0,
        invalid_count: 0,
        retryable_count: 0,
        created_at: '2026-10-31T00:00:00Z',
        updated_at: status === 'queued' ? '2026-10-31T00:00:00Z' : '2026-10-31T00:00:01Z',
        items: [{
            source_line: 1,
            label: 'Manual research key',
            suffix: '0001',
            status: status === 'queued' ? 'queued' : 'imported',
            attempts: status === 'queued' ? 0 : 1,
            retryable: false,
        }],
    };
}
