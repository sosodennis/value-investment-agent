import { expect, test, type Page } from '@playwright/test';
import { parseForwardEvidenceReview } from '../src/features/workspace/outputs/fundamental-analysis/forward-evidence-api';
import {
    baseResult,
    captureFundamentalArtifact,
    captureReport,
    closeInspector,
    historyIdentity,
    historyUrl,
    isRunStart,
    login,
    openInspector,
    readRun,
    readSnapshot,
    recordEvidence,
    requiredEnv,
    resolveRequiredTickerSelection,
    startAnalysis,
    verifySheetFocusCycle,
    verifyTechnicalIdentity,
    type CapturedReport,
    type RunIdentity,
} from './fundamental-report-live.helpers';

const baseButtonName = /^Inspect Deterministic base per share\b/;
const reportName = 'Fundamental valuation report';

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

function baseValueButton(page: Page) {
    return page.getByRole('article', { name: reportName }).getByRole('button', { name: baseButtonName });
}

async function waitForReport(page: Page, run: RunIdentity): Promise<CapturedReport> {
    await expect.poll(async () => {
        const snapshot = await readSnapshot(page, run);
        return snapshot.completed_outputs.some((item) => item.agent_id === 'fundamental_analysis' && item.artifact_id);
    }, { timeout: 180_000, intervals: [500, 1000, 2000] }).toBe(true);
    return captureReport(page, run);
}

function rawBase(captured: CapturedReport): string {
    const raw = baseResult(captured).per_share_value;
    if (!raw) throw new Error('The live valuation has no deterministic base per share.');
    return raw;
}

async function openHistory(page: Page): Promise<CapturedReport> {
    const run = historyIdentity();
    await page.goto(historyUrl(run));
    await page.getByRole('tab', { name: 'Fundamental', exact: true }).click();
    await expect(page.getByRole('article', { name: reportName })).toBeVisible({ timeout: 60_000 });
    const captured = await captureReport(page, run);
    expect(captured.artifactId).toBe(requiredEnv('FUNDAMENTAL_LIVE_HISTORY_ARTIFACT_ID'));
    return captured;
}

async function expectNoPageOverflow(page: Page): Promise<void> {
    const dimensions = await page.evaluate(() => ({
        viewport: document.documentElement.clientWidth,
        content: document.documentElement.scrollWidth,
    }));
    expect.soft(dimensions.content, 'Only local tables may scroll horizontally').toBeLessThanOrEqual(dimensions.viewport + 1);
    const box = await page.getByRole('article', { name: reportName }).boundingBox();
    expect(box).not.toBeNull();
    if (box) {
        expect.soft(box.x).toBeGreaterThanOrEqual(0);
        expect.soft(box.x + box.width).toBeLessThanOrEqual(dimensions.viewport + 1);
    }
}

function expectCurrentAnalysis(page: Page): void {
    const url = new URL(page.url());
    expect(url.pathname).toBe('/workspace');
    expect(url.searchParams.has('thread_id'), 'Revision keeps the current workspace owner').toBe(false);
    expect(url.searchParams.has('run_id'), 'Revision does not operate through a history route').toBe(false);
}

test.describe('Fundamental report against the real service', () => {
    test.skip(process.env.FUNDAMENTAL_LIVE !== '1', 'Requires an explicitly prepared live runtime. A skip is not acceptance evidence.');

    test.beforeAll(() => {
        for (const name of [
            'FUNDAMENTAL_LIVE_BASE_URL',
            'FUNDAMENTAL_LIVE_LOGIN_FILE',
            'FUNDAMENTAL_LIVE_HISTORY_THREAD_ID',
            'FUNDAMENTAL_LIVE_HISTORY_RUN_ID',
            'FUNDAMENTAL_LIVE_HISTORY_ARTIFACT_ID',
            'FUNDAMENTAL_LIVE_IMPLEMENTATION_COMMIT',
        ]) requiredEnv(name);
    });

    test.beforeEach(async ({ page }) => {
        await login(page);
    });

    test('draft stays separate, exact 2.5% revision creates a new read-only report', async ({ page }, info) => {
        const original = await waitForReport(page, await startAnalysis(page));
        const baseButton = baseValueButton(page);
        const previousDisplay = await baseButton.innerText();
        let runStarts = 0;
        page.on('request', (request) => {
            if (request.method() === 'POST' && /\/api\/v1\/threads\/[^/]+\/runs$/.test(new URL(request.url()).pathname)) runStarts += 1;
        });
        await page.getByLabel('Terminal growth (%)', { exact: true }).fill('2.5');
        await page.getByLabel('Reason for change', { exact: true }).fill('Live UI acceptance of a lower long-term growth assumption.');
        await expect(baseButton).toHaveText(previousDisplay);
        expect(runStarts, 'Editing the draft sends no valuation mutation').toBe(0);
        await recordEvidence(page, info, 'revision-draft', original, { draft: '2.5', previousDisplay, runStarts });

        const started = page.waitForResponse(isRunStart);
        expectCurrentAnalysis(page);
        await page.getByRole('button', { name: 'Recalculate', exact: true }).click();
        await expect(page.getByRole('button', { name: 'Recalculating…', exact: true })).toBeDisabled();
        await expect(baseButton).toHaveText(previousDisplay);
        await expect(page.getByRole('status').filter({ hasText: /previous|saved result/i }).first()).toBeVisible();
        const response = await started;
        const submitted: unknown = response.request().postDataJSON();
        expect(submitted).toMatchObject({ valuation_request: {
            contract_version: 'fundamental.v1',
            revision: {
                path: 'assumptions.terminal_growth',
                value: '0.025',
                source: {
                    thread_id: original.threadId,
                    run_id: original.runId,
                    artifact_id: original.artifactId,
                    preparation_digest: original.report.automatic_preparation?.preparation_digest,
                },
            },
        } });
        const revisedRun = await readRun(response);
        expect(revisedRun.threadId).toBe(original.threadId);
        expect(revisedRun.runId).not.toBe(original.runId);
        await resolveRequiredTickerSelection(page, revisedRun);
        const revised = await waitForReport(page, revisedRun);
        expect(revised.artifactId).not.toBe(original.artifactId);
        expect(revised.report.result_hash).not.toBe(original.report.result_hash);
        await expect(page.getByLabel('Terminal growth (%)', { exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: 'Recalculate', exact: true })).toHaveCount(0);
        expect(runStarts).toBe(1);

        const baseInspector = await openInspector(page, baseButton, rawBase(revised));
        await verifyTechnicalIdentity(baseInspector, revised, [baseResult(revised).result_hash, baseResult(revised).input_digest]);
        await closeInspector(page);
        const applied = revised.report.automatic_preparation?.assumptions_evidence.find(
            (item) => item.path === 'assumptions.terminal_growth' && item.method === 'manual',
        );
        if (!applied) throw new Error('The revised artifact has no applied manual terminal growth evidence.');
        expect(applied.value).toBe('0.025');
        const manualInspector = await openInspector(page, page.getByRole('region', { name: 'Key assumptions', exact: true }).getByRole('button', {
            name: /^Inspect Applied manual assumption · assumptions\.terminal_growth\b/,
        }), applied.value);
        await expect(manualInspector).toContainText(applied.path);
        await verifyTechnicalIdentity(manualInspector, revised, []);
        await closeInspector(page);
        const retained = original.report.automatic_preparation?.assumptions_evidence.find((item) => item.path === 'assumptions.terminal_growth');
        if (!retained) throw new Error('The original report has no terminal growth evidence.');
        const assumptions = page.getByRole('region', { name: 'Assumptions', exact: true });
        await assumptions.getByText(/^All assumptions \(\d+\)$/).click();
        const retainedInspector = await openInspector(page, assumptions.getByRole('button', {
            name: /^Inspect Original retained assumption · assumptions\.terminal_growth\b/,
        }), retained.value);
        await verifyTechnicalIdentity(retainedInspector, revised, []);
        await closeInspector(page);
        await recordEvidence(page, info, 'revision-completed', revised, {
            originalRunId: original.runId,
            originalArtifactId: original.artifactId,
            originalCreatedAt: original.createdAt,
            submittedRaw: '0.025',
            appliedRaw: applied.value,
            runStarts,
        });
    });

    test('real 5% refusal retains the previous report and draft', async ({ page }, info) => {
        const original = await waitForReport(page, await startAnalysis(page));
        const baseButton = baseValueButton(page);
        const previousDisplay = await baseButton.innerText();
        const reason = 'Live UI acceptance of the service manual-growth refusal.';
        await page.getByLabel('Terminal growth (%)', { exact: true }).fill('5');
        await page.getByLabel('Reason for change', { exact: true }).fill(reason);
        const started = page.waitForResponse(isRunStart);
        expectCurrentAnalysis(page);
        await page.getByRole('button', { name: 'Recalculate', exact: true }).click();
        const response = await started;
        const submitted: unknown = response.request().postDataJSON();
        expect(submitted).toMatchObject({ valuation_request: { revision: { value: '0.05' } } });
        const refusedRun = await readRun(response);
        expect(refusedRun.threadId).toBe(original.threadId);
        expect(refusedRun.runId).not.toBe(original.runId);
        await resolveRequiredTickerSelection(page, refusedRun);
        await expect(page.getByRole('alert').filter({ hasText: 'MANUAL_OVERRIDE_INVALID' }).first()).toBeVisible({ timeout: 180_000 });
        await expect(baseButton).toHaveText(previousDisplay);
        await expect(page.getByLabel('Terminal growth (%)', { exact: true })).toHaveValue('5');
        await expect(page.getByLabel('Reason for change', { exact: true })).toHaveValue(reason);
        const inspector = await openInspector(page, baseButton, rawBase(original));
        await verifyTechnicalIdentity(inspector, original, [baseResult(original).result_hash]);
        await closeInspector(page);
        await expect.poll(async () => (await readSnapshot(page, refusedRun)).run_status, {
            timeout: 180_000, intervals: [500, 1000, 2000],
        }).toBe('completed');
        const snapshot = await readSnapshot(page, refusedRun);
        expect(snapshot.run_status).toBe('completed');
        expect(snapshot.failure).toBeNull();
        const refused = await captureFundamentalArtifact(page, refusedRun);
        expect(refused.artifactId).not.toBe(original.artifactId);
        if (refused.report.projection_type !== 'degraded') throw new Error('The refused run must persist a degraded Fundamental artifact.');
        expect(refused.report.service_failure.code).toBe('MANUAL_OVERRIDE_INVALID');
        expect(refused.report.service_failure.message).toContain('0.04');
        expect(refused.report.service_failure.message).toContain('0.05');
        expect('service_result' in refused.report, 'A refusal contains no successful calculation').toBe(false);
        await recordEvidence(page, info, 'revision-refused', original, {
            refusedRunId: refusedRun.runId,
            refusedArtifactId: refused.artifactId,
            refusedArtifactUrl: refused.artifactUrl,
            refusal: refused.report.service_failure,
            retainedDraft: '5',
            previousDisplay,
            refusedRunStatus: snapshot.run_status,
        });
    });

    test('optional research terminates without changing the draft or promising Apply', async ({ page }, info) => {
        const original = await waitForReport(page, await startAnalysis(page));
        await page.getByLabel('Terminal growth (%)', { exact: true }).fill('2.5');
        await page.getByLabel('Reason for change', { exact: true }).fill('Keep this manual draft while researching external evidence.');
        await page.getByText('Research external evidence (optional)', { exact: true }).click();
        const responsePromise = page.waitForResponse((response) =>
            response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/fundamental/forward-evidence/research',
        );
        expectCurrentAnalysis(page);
        await page.getByRole('button', { name: 'Research external evidence', exact: true }).click();
        const response = await responsePromise;
        let outcome: object;
        if (response.ok()) {
            const payload: unknown = await response.json();
            const review = parseForwardEvidenceReview(payload);
            expect(review.accepted_claim_ids, 'This fixture exercises unavailable or no acceptable claim').toHaveLength(0);
            await expect(page.getByRole('region', { name: 'External evidence review' })).toBeVisible();
            outcome = { status: review.status, issueCodes: review.issue_codes, acceptedClaimCount: review.accepted_claim_ids.length };
        } else {
            await expect(page.getByRole('alert').first()).toBeVisible();
            outcome = { httpStatus: response.status(), status: 'error' };
        }
        await expect(page.getByRole('button', { name: 'Research external evidence', exact: true })).toBeEnabled();
        await expect(page.getByLabel('Terminal growth (%)', { exact: true })).toHaveValue('2.5');
        await expect(page.getByRole('button', { name: /^Apply/ })).toHaveCount(0);
        await recordEvidence(page, info, 'research-terminated', original, { ...outcome, retainedDraft: '2.5' });
    });

    test('history is immutable and exact raw values remain inspectable', async ({ page }, info) => {
        let mutations = 0;
        page.on('request', (request) => {
            if (request.method() !== 'GET' && /\/api\/v1\/(threads|fundamental)\//.test(new URL(request.url()).pathname)) mutations += 1;
        });
        const captured = await openHistory(page);
        await expect(page.getByLabel('Terminal growth (%)', { exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: 'Recalculate', exact: true })).toHaveCount(0);
        const inspector = await openInspector(page, baseValueButton(page), rawBase(captured));
        await verifyTechnicalIdentity(inspector, captured, [baseResult(captured).result_hash, baseResult(captured).input_digest]);
        await closeInspector(page);
        const service = captured.report.service_result;
        if (!('base' in service) || !service.quantiles?.p50) throw new Error('The live history fixture requires MC p50.');
        const quantileInspector = await openInspector(page, page.getByRole('button', {
            name: /^Inspect Model quantile · p50\b/,
        }), service.quantiles.p50);
        await verifyTechnicalIdentity(quantileInspector, captured, [service.result_hash]);
        await closeInspector(page);

        await page.getByText(/^All financial facts \(\d+\)$/).click();
        const revenue = captured.report.facts.facts.find((fact) => fact.normalized_field === 'revenue');
        if (!revenue || typeof revenue.value !== 'string') throw new Error('The live history fixture requires a numeric revenue fact.');
        const revenueRow = page.getByRole('row').filter({ has: page.getByText(revenue.fact_id, { exact: true }) });
        const revenueInspector = await openInspector(page, revenueRow.getByRole('button', {
            name: /^Inspect Service fact · revenue\b/,
        }), revenue.value);
        await verifyTechnicalIdentity(revenueInspector, captured, [revenue.fact_id, revenue.source.content_hash]);
        await closeInspector(page);

        await page.locator('summary').filter({ hasText: /^Sources & method$/ }).click();
        const node = baseResult(captured).nodes.find((item) => item.node_id === 'revenue_1');
        if (!node?.value) throw new Error('The live history fixture requires the first revenue projection node.');
        const nodeInspector = await openInspector(page, page.getByRole('button', {
            name: /^Inspect Calculation · revenue_1\b/,
        }).first(), node.value);
        await verifyTechnicalIdentity(nodeInspector, captured, [baseResult(captured).result_hash]);
        await expect(nodeInspector).toContainText(node.formula);
        await closeInspector(page);

        await page.getByText('Service scenarios and diagnostics', { exact: true }).click();
        const scenario = service.scenario_results[0];
        if (!scenario?.per_share_value) throw new Error('The live history fixture requires a service scenario per-share result.');
        const scenarioInspector = await openInspector(page, page.getByRole('button', {
            name: /^Inspect Service scenario 1 per share\b/,
        }), scenario.per_share_value);
        await verifyTechnicalIdentity(scenarioInspector, captured, [scenario.result_hash, scenario.input_digest]);
        await closeInspector(page);
        expect(mutations, 'Reading history and evidence sends no workflow mutation').toBe(0);
        await recordEvidence(page, info, 'history-read-only', captured, {
            mutations,
            rawBase: rawBase(captured),
            p50: service.quantiles.p50,
            factId: revenue.fact_id,
            sourceScale: revenue.scale,
            nodeId: node.node_id,
            scenarioResultHash: scenario.result_hash,
        });
    });

    test('real history reflows in light and dark with reduced motion and a narrow report pane', async ({ page }, info) => {
        const captured = await openHistory(page);
        await page.emulateMedia({ reducedMotion: 'reduce' });
        expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
        for (const theme of ['light', 'dark']) {
            await page.evaluate((value) => {
                localStorage.setItem('theme', value);
            }, theme);
            await page.reload();
            await page.getByRole('tab', { name: 'Fundamental', exact: true }).click();
            await expect(page.locator('html')).toHaveClass(new RegExp(`\\b${theme}\\b`));
            for (const width of [320, 390, 768, 1440]) {
                await page.setViewportSize({ width, height: 1000 });
                await expect(baseValueButton(page)).toBeVisible();
                await expectNoPageOverflow(page);
                await recordEvidence(page, info, `layout-${theme}-${width}`, captured, { theme, viewportWidth: width, reducedMotion: true });
            }
        }
        const report = page.getByRole('article', { name: reportName });
        const before = await report.boundingBox();
        const separator = page.getByRole('separator', { name: 'Resize workspace panel' }).last();
        await separator.focus();
        for (let index = 0; index < 12; index += 1) await separator.press('ArrowLeft');
        const after = await report.boundingBox();
        expect(before).not.toBeNull();
        expect(after).not.toBeNull();
        if (before && after) expect(after.width).toBeLessThan(before.width);
        await expectNoPageOverflow(page);
        await recordEvidence(page, info, 'layout-independent-narrow-pane', captured, { before, after });
        await page.setViewportSize({ width: 390, height: 1000 });
        await verifySheetFocusCycle(page, baseValueButton(page));
        await recordEvidence(page, info, 'sheet-keyboard-focus-cycle', captured, { forwardCycle: true, reverseCycle: true, escape: true, focusReturn: true });
    });

    test('touch opens and closes exact-run evidence', async ({ browser }, info) => {
        const context = await browser.newContext({
            baseURL: process.env.FUNDAMENTAL_LIVE_BASE_URL,
            viewport: { width: 390, height: 844 },
            isMobile: true,
            hasTouch: true,
        });
        try {
            const page = await context.newPage();
            await login(page);
            const captured = await openHistory(page);
            const trigger = baseValueButton(page);
            await trigger.tap();
            const dialog = page.getByRole('dialog');
            await expect(dialog).toBeVisible();
            await expect(dialog.getByLabel('Original value · full precision', { exact: true })).toHaveValue(rawBase(captured));
            await recordEvidence(page, info, 'touch-evidence', captured, { hasTouch: true, viewportWidth: 390 });
            await dialog.getByRole('button', { name: 'Close evidence inspector', exact: true }).tap();
            await expect(dialog).not.toBeVisible();
        } finally {
            await context.close();
        }
    });
});
