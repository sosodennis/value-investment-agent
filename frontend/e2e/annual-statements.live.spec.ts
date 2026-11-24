import { expect, test } from '@playwright/test';
import { parseArtifactEnvelope } from '../src/types/agents/artifact-envelope-parser';
import { parseFundamentalArtifact } from '../src/types/agents/artifact-parsers';
import { object, nonEmpty } from '../src/types/agents/fundamental-parser-primitives';
import type { components } from '../src/types/generated/api-contract';
import { closeInspector, login, requiredEnv } from './fundamental-report-live.helpers';

type Contracts = components['schemas'];
const parseRead = object<Contracts['AnnualStatementArtifactResponse']>({ thread_id: nonEmpty, reference: object<Contracts['ArtifactReference']>({ artifact_id: nonEmpty, download_url: nonEmpty, type: nonEmpty }) });
const STATEMENT_TITLES = { income_statement: 'Income statement', balance_sheet: 'Balance sheet', cash_flow: 'Cash flow statement' };

test.describe('Annual statement production reader', () => {
    test.setTimeout(360_000);
    test.skip(process.env.ANNUAL_STATEMENTS_LIVE !== '1', 'Requires a real published statement release and isolated application.');

    test('reads a new owned workspace, inspects every cell and reopens the saved statement with keyboard and touch', async ({ page, browser }, info) => {
        let runStarts = 0;
        let statementReads = 0;
        page.on('request', (request) => {
            if (request.method() === 'POST' && /\/api\/v1\/threads\/[^/]+\/runs$/.test(new URL(request.url()).pathname)) runStarts += 1;
            if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/fundamental/annual-statements/read') statementReads += 1;
        });
        await login(page);
        await page.setViewportSize({ width: 1335, height: 1000 });
        await page.goto('/workspace');
        await page.getByRole('tab', { name: 'Fundamental', exact: true }).click();
        await page.getByRole('combobox', { name: 'Statement company' }).click();
        const issuerId = requiredEnv('ANNUAL_STATEMENTS_LIVE_ISSUER_ID');
        await page.getByRole('option').filter({ hasText: issuerId }).click();
        const readResponse = page.waitForResponse((response) => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/annual-statements/read'));
        await page.getByRole('button', { name: 'Read prepared statements' }).click();
        const response = await readResponse;
        expect(response.status()).toBe(200);
        const readPayload: unknown = await response.json();
        const saved = parseRead(readPayload, 'live statement read');
        expect(saved.reference.download_url).not.toContain('run_id');
        const artifactResponse = await page.request.get(saved.reference.download_url);
        expect(artifactResponse.status()).toBe(200);
        const artifactPayload: unknown = await artifactResponse.json();
        const artifact = parseFundamentalArtifact(parseArtifactEnvelope(artifactPayload, 'live statement artifact', 'financial_reports').data);
        const annual = artifact.annual_statements;
        if (!annual) throw new Error('The real artifact must contain annual statements.');
        expect(annual.statements.scope.issuer_id).toBe(issuerId);
        const report = page.getByRole('article', { name: 'Annual financial statements' });
        await expect(report).toBeVisible();
        let inspectedReported = 0;
        let inspectedUnavailable = 0;
        const inspectedCellIds: string[] = [];
        for (const table of annual.statements.tables) {
            const name = STATEMENT_TITLES[table.statement];
            const section = report.getByRole('region', { name, exact: true });
            expect(table.rows.some((row) => row.cells.some((cell) => cell.status === 'reported')), `${name} has reported values`).toBe(true);
            for (const row of table.rows) {
                for (const [index, cell] of row.cells.entries()) {
                    const column = table.columns[index];
                    if (!column) throw new Error('The service row has no corresponding period.');
                    const trigger = section.getByRole('button', { name: `Inspect ${row.definition.label} · ${column.fiscal_label}`, exact: true });
                    await expect(trigger).toBeVisible();
                    await trigger.focus();
                    await trigger.press('Enter');
                    const sheet = page.getByRole('dialog');
                    await expect(sheet).toBeVisible();
                    const inspector = sheet.getByRole('complementary', { name: 'Evidence inspector' });
                    const rawValue = inspector.getByLabel('Original value · full precision', { exact: true });
                    if (cell.status === 'reported') {
                        if (!cell.fact.accession_number) throw new Error('A reported filing value must retain its accession.');
                        await expect(rawValue).toHaveValue(cell.fact.value);
                        await expect(inspector).toContainText(cell.fact.accession_number);
                        await expect(inspector).toContainText(cell.fact.unit);
                        await expect(inspector.getByRole('link', { name: 'Open source document', exact: true })).toHaveAttribute('href', cell.fact.source.source_url);
                        inspectedReported += 1;
                    } else {
                        await expect(rawValue).toHaveValue(`${cell.missing.status} · ${cell.missing.reason}`);
                        inspectedUnavailable += 1;
                    }
                    await inspector.getByText('Technical identity', { exact: true }).click();
                    await expect(inspector).toContainText(annual.statements.statement_id);
                    await expect(inspector).toContainText(cell.cell_id);
                    await expect(inspector).toContainText(cell.period_id);
                    if (cell.status === 'reported') {
                        await expect(inspector).toContainText(cell.selected_version_id);
                        await expect(inspector).toContainText(cell.fact.context.context_id);
                        await expect(inspector).toContainText(cell.fact.source.content_hash);
                        await expect(inspector).toContainText(cell.mapping_digest);
                    }
                    await closeInspector(page);
                    await expect(sheet).toBeHidden();
                    await expect(trigger).toBeFocused();
                    inspectedCellIds.push(cell.cell_id);
                }
            }
        }
        const savedUrl = page.url();
        expect(savedUrl).toContain(`statement_artifact=${saved.reference.artifact_id}`);
        expect(statementReads).toBe(1);
        const priorReads = statementReads;
        await page.reload();
        await expect(report).toBeVisible();
        expect(statementReads).toBe(priorReads);
        expect(runStarts).toBe(0);
        for (const theme of ['Light', 'Dark']) {
            await page.getByRole('button', { name: 'Change color theme' }).click();
            await page.getByRole('menuitemradio', { name: theme, exact: true }).click();
            for (const width of [320, 390, 768, 1440]) {
                await page.setViewportSize({ width, height: 1000 });
                await expect(report).toBeVisible();
                await report.getByRole('heading', { level: 2 }).scrollIntoViewIfNeeded();
                expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Page fits at ${width}px in ${theme}`).toBe(true);
                const table = report.getByRole('region', { name: 'Income statement table', exact: true });
                if (width === 320) {
                    await table.focus();
                    await page.keyboard.press('ArrowRight');
                    await expect.poll(() => table.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
                }
                await page.screenshot({ path: info.outputPath(`annual-statements-${theme.toLowerCase()}-${width}.png`) });
            }
        }
        const touchContext = await browser.newContext({
            baseURL: requiredEnv('FUNDAMENTAL_LIVE_BASE_URL'),
            storageState: await page.context().storageState(),
            viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true,
        });
        let touchReads = 0;
        let touchRunStarts = 0;
        try {
            const touchPage = await touchContext.newPage();
            touchPage.on('request', (request) => {
                if (request.method() === 'POST' && /\/api\/v1\/threads\/[^/]+\/runs$/.test(new URL(request.url()).pathname)) touchRunStarts += 1;
                if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/fundamental/annual-statements/read') touchReads += 1;
            });
            await touchPage.goto(savedUrl);
            const touchReport = touchPage.getByRole('article', { name: 'Annual financial statements' });
            await expect(touchReport).toBeVisible();
            expect(await touchPage.evaluate(() => window.innerWidth)).toBe(390);
            for (const table of annual.statements.tables) {
                const row = table.rows.find((item) => item.cells.some((cell) => cell.status === 'reported'));
                const index = row?.cells.findIndex((cell) => cell.status === 'reported') ?? -1;
                const cell = row?.cells[index];
                const column = table.columns[index];
                if (!row || cell?.status !== 'reported' || !column) throw new Error('Each touch table requires a reported source cell.');
                const section = touchReport.getByRole('region', { name: STATEMENT_TITLES[table.statement], exact: true });
                const trigger = section.getByRole('button', { name: `Inspect ${row.definition.label} · ${column.fiscal_label}`, exact: true });
                await trigger.tap();
                const sheet = touchPage.getByRole('dialog');
                await expect(sheet).toBeVisible();
                await expect(sheet.getByLabel('Original value · full precision', { exact: true })).toHaveValue(cell.fact.value);
                expect(await touchPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'The touch inspector fits the page').toBe(true);
                await sheet.getByRole('button', { name: 'Close evidence inspector', exact: true }).tap();
                await expect(sheet).toBeHidden();
                await expect(trigger).toBeFocused();
            }
            expect(await touchPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'The touch report fits the page').toBe(true);
            await touchReport.getByRole('heading', { level: 2 }).scrollIntoViewIfNeeded();
            await touchPage.screenshot({ path: info.outputPath('annual-statements-touch-390.png') });
            expect(touchReads).toBe(0);
            expect(touchRunStarts).toBe(0);
        } finally {
            await touchContext.close();
        }
        expect(runStarts).toBe(0);
        expect(statementReads).toBe(priorReads);
        await info.attach('saved-statement-identity', { body: JSON.stringify({ thread_id: saved.thread_id, reference: saved.reference, statement_id: annual.statements.statement_id, manifest: annual.data_release_manifest_digest, cutoff_at: annual.statements.cutoff_at, inspectedCellIds, inspectedReported, inspectedUnavailable, runStarts, statementReads, touchRunStarts, touchReads }), contentType: 'application/json' });
    });
});
