import { expect, test } from '@playwright/test';
import { baseResult, captureReport, closeInspector, historyIdentity, historyUrl, login, requiredEnv, verifyTechnicalIdentity } from './fundamental-report-live.helpers';

test.describe('Fundamental report reading regression', () => {
    test.setTimeout(60_000);
    test.use({ actionTimeout: 15_000 });
    test.skip(process.env.FUNDAMENTAL_LIVE !== '1', 'Requires an authenticated retained report in the isolated application.');

    test('financial amounts and source periods remain whole inside a locally scrollable table', async ({ page }) => {
        await login(page);
        await page.setViewportSize({ width: 1335, height: 1000 });
        await page.goto(historyUrl(historyIdentity()));
        await page.getByRole('tab', { name: 'Fundamental', exact: true }).click();
        const report = page.getByRole('article', { name: 'Fundamental valuation report' });
        await expect(report).toBeVisible();
        await report.getByText(/^All financial facts \(/).click();
        const region = report.getByRole('region', { name: 'Financial facts table', exact: true });
        for (const width of [1440, 1335, 768, 390, 320]) {
            await page.setViewportSize({ width, height: 1000 });
            const rows = await region.locator('tbody tr').evaluateAll((elements) => elements.map((row) => {
                const cells = row.querySelectorAll('td');
                const value = cells[1]?.querySelector('button');
                const period = cells[2];
                function lineCount(element: Element | null | undefined) {
                    if (!element) return 0;
                    const range = document.createRange();
                    range.selectNodeContents(element);
                    return new Set([...range.getClientRects()].map((rect) => Math.round(rect.top))).size;
                }
                return { value: value?.textContent, valueLines: lineCount(value), periodLines: lineCount(period) };
            }));
            expect(rows.length).toBeGreaterThan(0);
            expect(rows.filter((row) => row.valueLines !== 1), `Amounts stay whole at ${width}px`).toEqual([]);
            expect(rows.filter((row) => row.periodLines !== 1), `ISO periods stay whole at ${width}px`).toEqual([]);
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
            if (width === 320) {
                const scroll = await region.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }));
                expect(scroll.scroll, 'The named keyboard-focusable region owns horizontal scrolling').toBeGreaterThan(scroll.client);
                await region.focus();
                await page.keyboard.press('ArrowRight');
                await expect.poll(() => region.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
            }
        }
    });

    test('plotted forecast and Monte Carlo marks support hover, keyboard and exact source inspection', async ({ page }, info) => {
        let mutations = 0;
        page.on('request', (request) => {
            if (request.method() !== 'GET' && /\/api\/v1\/(threads|fundamental)\//.test(new URL(request.url()).pathname)) mutations += 1;
        });
        await login(page);
        await page.goto(historyUrl(historyIdentity()));
        await page.getByRole('tab', { name: 'Fundamental', exact: true }).click();
        const captured = await captureReport(page, historyIdentity());
        const base = baseResult(captured);
        const revenue = base.nodes.find((node) => node.node_id === 'revenue_1');
        const uncertainty = captured.report.service_result;
        if (!revenue?.value || !('base' in uncertainty) || !uncertainty.quantiles?.p50 || !base.per_share_value) {
            throw new Error('Retained report must have a forecast, Base and P50.');
        }
        const chart = page.getByRole('figure', { name: 'Revenue trend', exact: true }).first();
        const point = chart.getByRole('button', { name: /^Inspect Revenue · Year 1 ·/ });
        await point.hover();
        await expect(chart.getByRole('status')).toContainText('Year 1');
        await point.focus();
        await expect(point).toBeFocused();
        await point.press('Enter');
        const inspector = page.getByRole('complementary', { name: 'Evidence inspector' });
        await expect(inspector.getByLabel('Original value · full precision', { exact: true })).toHaveValue(revenue.value);
        await verifyTechnicalIdentity(inspector, captured, [base.result_hash, base.input_digest]);
        await expect(inspector).toContainText(revenue.formula);
        await closeInspector(page);

        const historical = captured.report.facts.facts.filter((fact) => fact.normalized_field === 'revenue')
            .sort((left, right) => left.period_end.localeCompare(right.period_end))[0];
        if (!historical || typeof historical.value !== 'string') throw new Error('Retained report must have historical revenue.');
        const historicalChart = page.getByRole('figure', { name: 'Revenue trend', exact: true }).nth(1);
        const historicalPoint = historicalChart.getByRole('button', { name: new RegExp(`^Inspect Revenue · ${historical.period_end} ·`) });
        await historicalPoint.click();
        await expect(inspector.getByLabel('Original value · full precision', { exact: true })).toHaveValue(historical.value);
        await verifyTechnicalIdentity(inspector, captured, [historical.fact_id, historical.source.content_hash]);
        await closeInspector(page);

        const monteCarlo = page.getByRole('figure', { name: 'Service quantile markers', exact: true });
        for (const [label, raw, hash] of [
            ['P50', uncertainty.quantiles.p50, uncertainty.result_hash],
            ['Deterministic base', base.per_share_value, base.result_hash],
        ]) {
            const mark = monteCarlo.getByRole('button', { name: new RegExp(`^Inspect ${label} ·`) });
            await mark.hover();
            await expect(monteCarlo.getByRole('status')).toContainText(label);
            await mark.focus();
            await mark.press('Space');
            await expect(inspector.getByLabel('Original value · full precision', { exact: true })).toHaveValue(raw);
            await verifyTechnicalIdentity(inspector, captured, [hash]);
            await closeInspector(page);
        }
        await monteCarlo.scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath('quantile-range.png') });
        expect(mutations, 'Reading chart points keeps retained history immutable').toBe(0);
    });

    test('touch targets inspect quantile and forecast values in a narrow report', async ({ browser }) => {
        const context = await browser.newContext({ baseURL: requiredEnv('FUNDAMENTAL_LIVE_BASE_URL'), viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
        try {
            const page = await context.newPage();
            await login(page);
            await page.goto(historyUrl(historyIdentity()));
            await page.getByRole('tab', { name: 'Fundamental', exact: true }).tap();
            const captured = await captureReport(page, historyIdentity());
            const revenue = baseResult(captured).nodes.find((node) => node.node_id === 'revenue_1');
            const result = captured.report.service_result;
            if (!revenue?.value || !('base' in result) || !result.quantiles?.p05) throw new Error('Retained chart values are required.');
            const marks = [
                { figure: 'Service quantile markers', label: /^Inspect P05 ·/, raw: result.quantiles.p05 },
                { figure: 'Revenue trend', label: /^Inspect Revenue · Year 1 ·/, raw: revenue.value },
            ];
            for (const mark of marks) {
                const trigger = page.getByRole('figure', { name: mark.figure, exact: true }).first().getByRole('button', { name: mark.label });
                await trigger.tap();
                const sheet = page.getByRole('dialog');
                await expect(sheet).toBeVisible();
                await expect(sheet.getByLabel('Original value · full precision', { exact: true })).toHaveValue(mark.raw);
                await page.keyboard.press('Escape');
                await expect(sheet).toBeHidden();
                await expect(trigger).toBeFocused();
            }
        } finally {
            await context.close();
        }
    });
});
