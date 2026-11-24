import { expect, test } from '@playwright/test';
import { parseArtifactEnvelope } from '../src/types/agents/artifact-envelope-parser';
import { parseFundamentalArtifact } from '../src/types/agents/artifact-parsers';
import { object, nonEmpty } from '../src/types/agents/fundamental-parser-primitives';
import type { components } from '../src/types/generated/api-contract';
import { closeInspector, login, requiredEnv } from './fundamental-report-live.helpers';

type Contracts = components['schemas'];
const parseRead = object<Contracts['AnnualStatementArtifactResponse']>({ thread_id: nonEmpty, reference: object<Contracts['ArtifactReference']>({ artifact_id: nonEmpty, download_url: nonEmpty, type: nonEmpty }) });

test.describe('Annual statement production reader', () => {
    test.setTimeout(120_000);
    test.skip(process.env.ANNUAL_STATEMENTS_LIVE !== '1', 'Requires a real published statement release and isolated application.');

    test('reads a new owned workspace, inspects source cells and reopens the exact saved statement', async ({ page }, info) => {
        let runStarts = 0;
        let statementReads = 0;
        page.on('request', (request) => {
            if (request.method() === 'POST' && /\/api\/v1\/threads\/[^/]+\/runs$/.test(new URL(request.url()).pathname)) runStarts += 1;
            if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/fundamental/annual-statements/read') statementReads += 1;
        });
        await login(page);
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
        for (const table of annual.statements.tables) {
            const name = table.statement === 'income_statement' ? 'Income statement' : table.statement === 'balance_sheet' ? 'Balance sheet' : 'Cash flow statement';
            const section = report.getByRole('region', { name, exact: true });
            for (const row of table.rows) {
                for (const index of row.cells.keys()) {
                    const column = table.columns[index];
                    if (!column) throw new Error('The service row has no corresponding period.');
                    const trigger = section.getByRole('button', { name: `Inspect ${row.definition.label} · ${column.fiscal_label}`, exact: true });
                    await expect(trigger).toBeVisible();
                }
            }
            const row = table.rows.find((item) => item.cells.some((cell) => cell.status === 'reported'));
            const index = row?.cells.findIndex((cell) => cell.status === 'reported') ?? -1;
            const cell = row?.cells[index];
            const column = table.columns[index];
            if (!row || cell?.status !== 'reported' || !column) throw new Error(`A positive ${name} cell is required.`);
            const trigger = section.getByRole('button', { name: `Inspect ${row.definition.label} · ${column.fiscal_label}`, exact: true });
            await trigger.focus();
            await trigger.press('Enter');
            const inspector = page.getByRole('complementary', { name: 'Evidence inspector' });
            await expect(inspector.getByLabel('Original value · full precision')).toHaveValue(cell.fact.value);
            await inspector.getByText('Technical identity', { exact: true }).click();
            await expect(inspector).toContainText(cell.fact.context.context_id);
            await expect(inspector).toContainText(cell.fact.source.content_hash);
            await expect(inspector).toContainText(cell.mapping_digest);
            await closeInspector(page);
            await expect(trigger).toBeFocused();
        }
        const savedUrl = page.url();
        expect(savedUrl).toContain(`statement_artifact=${saved.reference.artifact_id}`);
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
        await info.attach('saved-statement-identity', { body: JSON.stringify({ thread_id: saved.thread_id, reference: saved.reference, statement_id: annual.statements.statement_id, manifest: annual.data_release_manifest_digest, cutoff_at: annual.statements.cutoff_at, runStarts, statementReads }), contentType: 'application/json' });
    });
});
