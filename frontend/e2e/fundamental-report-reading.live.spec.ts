import { expect, test } from '@playwright/test';
import { historyIdentity, historyUrl, login } from './fundamental-report-live.helpers';

test.describe('Fundamental report reading regression', () => {
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
        for (const width of [1335, 768, 390, 320]) {
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
                await page.keyboard.press('End');
                await expect.poll(() => region.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
            }
        }
    });
});
