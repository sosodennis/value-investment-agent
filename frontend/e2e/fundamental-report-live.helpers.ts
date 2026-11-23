import { readFile, writeFile } from 'node:fs/promises';
import { expect, type Locator, type Page, type Response, type TestInfo } from '@playwright/test';
import { parseArtifactEnvelope } from '../src/types/agents/artifact-envelope-parser';
import { parseFundamentalArtifact } from '../src/types/agents/artifact-parsers';
import type { FundamentalServiceArtifact } from '../src/types/agents/fundamental-service-facts';
import { parseWorkflowActivitySnapshot } from '../src/features/workflow/workflow-activity';

export type RunIdentity = { threadId: string; runId: string };
type ValuationReport = Extract<FundamentalServiceArtifact, { projection_type: 'valuation' }>;
export type CapturedArtifact = RunIdentity & {
    artifactId: string;
    artifactUrl: string;
    createdAt: string;
    report: FundamentalServiceArtifact;
};
export type CapturedReport = CapturedArtifact & { report: ValuationReport };

export function requiredEnv(name: string): string {
    const value = process.env[name];
    if (!value) throw new Error(`${name} is required when FUNDAMENTAL_LIVE=1.`);
    return value;
}

export function historyIdentity(): RunIdentity {
    return {
        threadId: requiredEnv('FUNDAMENTAL_LIVE_HISTORY_THREAD_ID'),
        runId: requiredEnv('FUNDAMENTAL_LIVE_HISTORY_RUN_ID'),
    };
}

export function historyUrl(run: RunIdentity): string {
    return `/workspace?${new URLSearchParams({ thread_id: run.threadId, run_id: run.runId })}`;
}

export async function login(page: Page): Promise<void> {
    requiredEnv('FUNDAMENTAL_LIVE_BASE_URL');
    const credentials: unknown = JSON.parse(await readFile(requiredEnv('FUNDAMENTAL_LIVE_LOGIN_FILE'), 'utf8'));
    if (typeof credentials !== 'object' || credentials === null ||
        !('email' in credentials) || typeof credentials.email !== 'string' ||
        !('password' in credentials) || typeof credentials.password !== 'string') {
        throw new Error('The live login file must contain email and password strings.');
    }
    const response = await page.request.post('/api/v1/auth/login', {
        data: { email: credentials.email, password: credentials.password },
    });
    if (!response.ok()) throw new Error(`Live login failed with HTTP ${response.status()}.`);
}

export function isRunStart(response: Response): boolean {
    return response.request().method() === 'POST' && /\/api\/v1\/threads\/[^/]+\/runs$/.test(new URL(response.url()).pathname);
}

export async function readRun(response: Response): Promise<RunIdentity> {
    expect(response.status(), 'The real service accepted the run').toBe(202);
    const value: unknown = await response.json();
    if (typeof value !== 'object' || value === null ||
        !('thread_id' in value) || typeof value.thread_id !== 'string' || !value.thread_id ||
        !('run_id' in value) || typeof value.run_id !== 'string' || !value.run_id) {
        throw new Error('The real run response did not contain a complete identity.');
    }
    return { threadId: value.thread_id, runId: value.run_id };
}

export async function startAnalysis(page: Page): Promise<RunIdentity> {
    await page.goto('/workspace');
    await page.getByLabel('Company ticker').fill('MSFT');
    const started = page.waitForResponse(isRunStart);
    await page.getByRole('button', { name: 'Start analysis', exact: true }).click();
    const run = await readRun(await started);
    await expect.poll(async () => {
        const snapshot = await readSnapshot(page, run);
        return snapshot.pending_interactions.some((item) => item.kind === 'ticker_selection' && item.status === 'pending') ||
            snapshot.completed_outputs.some((item) => item.agent_id === 'fundamental_analysis');
    }, { timeout: 180_000, intervals: [500, 1000, 2000] }).toBe(true);
    const snapshot = await readSnapshot(page, run);
    if (snapshot.pending_interactions.some((item) => item.kind === 'ticker_selection' && item.status === 'pending')) {
        const candidate = page.getByRole('radio', { name: /^MSFT\s/ });
        await expect(candidate).toHaveCount(1);
        await expect(candidate).toHaveAccessibleName(/NASDAQ/i);
        await candidate.check();
        await page.getByRole('button', { name: 'Continue with MSFT', exact: true }).click();
    }
    await page.getByRole('tab', { name: 'Fundamental', exact: true }).click();
    await expect(page.getByRole('article', { name: 'Fundamental valuation report' })).toBeVisible({ timeout: 180_000 });
    await expect(page.getByLabel('Terminal growth (%)', { exact: true })).toBeEnabled({ timeout: 180_000 });
    return run;
}

export async function readSnapshot(page: Page, run: RunIdentity) {
    const snapshotResponse = await page.request.get(
        `/api/v1/threads/${encodeURIComponent(run.threadId)}/activities?${new URLSearchParams({ run_id: run.runId })}`,
    );
    expect(snapshotResponse.ok(), 'Real activity snapshot is readable').toBe(true);
    const payload: unknown = await snapshotResponse.json();
    const snapshot = parseWorkflowActivitySnapshot(payload);
    expect(snapshot.thread_id).toBe(run.threadId);
    expect(snapshot.run_id).toBe(run.runId);
    return snapshot;
}

export async function captureFundamentalArtifact(page: Page, run: RunIdentity): Promise<CapturedArtifact> {
    const snapshot = await readSnapshot(page, run);
    const output = snapshot.completed_outputs.find((item) => item.agent_id === 'fundamental_analysis');
    if (!output?.artifact_id) throw new Error('The run has no persisted Fundamental artifact yet.');
    expect(output.identity.thread_id).toBe(run.threadId);
    expect(output.identity.run_id).toBe(run.runId);
    const artifactUrl = `/api/v1/artifacts/${encodeURIComponent(output.artifact_id)}?${new URLSearchParams({ run_id: run.runId })}`;
    const response = await page.request.get(artifactUrl);
    expect(response.ok(), 'The exact-run artifact is readable').toBe(true);
    const envelopePayload: unknown = await response.json();
    const envelope = parseArtifactEnvelope(envelopePayload, 'live artifact', 'financial_reports');
    const parsed = parseFundamentalArtifact(envelope.data);
    if (!parsed.fundamental_service) throw new Error('The persisted artifact has no typed Fundamental service projection.');
    expect(parsed.ticker).toBe('MSFT');
    return { ...run, artifactId: output.artifact_id, artifactUrl, createdAt: envelope.created_at, report: parsed.fundamental_service };
}

export async function captureReport(page: Page, run: RunIdentity): Promise<CapturedReport> {
    const captured = await captureFundamentalArtifact(page, run);
    if (captured.report.projection_type !== 'valuation') {
        throw new Error('The live fixture must produce a typed valuation report.');
    }
    return { ...captured, report: captured.report };
}

export function baseResult(captured: CapturedReport) {
    const result = captured.report.service_result;
    return 'base' in result ? result.base : result;
}

export async function openInspector(page: Page, button: Locator, raw: string): Promise<Locator> {
    await button.click();
    const inspector = page.getByRole('complementary', { name: 'Evidence inspector' });
    await expect(inspector.getByLabel('Original value · full precision', { exact: true })).toHaveValue(raw);
    return inspector;
}

export async function verifyTechnicalIdentity(inspector: Locator, captured: CapturedReport, expected: string[]): Promise<void> {
    const summary = inspector.getByText('Technical identity', { exact: true });
    const technical = inspector.locator('details').filter({ has: summary });
    if (await technical.getAttribute('open') === null) await summary.click();
    await expect(technical).toContainText(captured.threadId);
    await expect(technical).toContainText(captured.runId);
    await expect(technical).toContainText(captured.artifactId);
    for (const value of expected) await expect(technical).toContainText(value);
}

export async function closeInspector(page: Page): Promise<void> {
    const dialog = page.getByRole('dialog');
    if (await dialog.isVisible()) await page.keyboard.press('Escape');
}

export async function verifySheetFocusCycle(page: Page, trigger: Locator): Promise<void> {
    await trigger.focus();
    await trigger.press('Enter');
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const focusable = dialog.locator('button:visible:not(:disabled), a[href]:visible, textarea:visible:not(:disabled), input:visible:not(:disabled), select:visible:not(:disabled), summary:visible, [tabindex="0"]:visible');
    const count = await focusable.count();
    expect(count).toBeGreaterThan(1);
    await focusable.first().focus();
    for (let index = 0; index < count; index += 1) {
        await page.keyboard.press('Tab');
        expect(await dialog.evaluate((element) => element.contains(document.activeElement)), 'Forward focus stays inside the sheet').toBe(true);
    }
    await expect(focusable.first()).toBeFocused();
    for (let index = 0; index < count; index += 1) {
        await page.keyboard.press('Shift+Tab');
        expect(await dialog.evaluate((element) => element.contains(document.activeElement)), 'Reverse focus stays inside the sheet').toBe(true);
    }
    await expect(focusable.first()).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
}

export async function recordEvidence(page: Page, info: TestInfo, name: string, captured: CapturedReport, observations: object): Promise<void> {
    const evidencePath = info.outputPath(`${name}.json`);
    const screenshotPath = info.outputPath(`${name}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    const result = baseResult(captured);
    await writeFile(evidencePath, JSON.stringify({
        implementationCommit: requiredEnv('FUNDAMENTAL_LIVE_IMPLEMENTATION_COMMIT'),
        observedAt: new Date().toISOString(),
        url: page.url(),
        threadId: captured.threadId,
        runId: captured.runId,
        artifactId: captured.artifactId,
        artifactUrl: captured.artifactUrl,
        createdAt: captured.createdAt,
        preparationDigest: captured.report.automatic_preparation?.preparation_digest,
        resultHash: captured.report.result_hash,
        basePerShare: result.per_share_value,
        quantiles: 'quantiles' in captured.report.service_result ? captured.report.service_result.quantiles : null,
        quality: captured.report.quality_status,
        calculationStatus: result.calculation_status,
        evaluatedAt: result.evaluated_at,
        valuationTimestamp: result.valuation_timestamp,
        factCount: captured.report.facts.facts.length,
        observations,
        manualChecksRequired: ['native 200% browser zoom', 'screen reader', 'system clipboard paste'],
    }, null, 2));
    await info.attach(name, { path: evidencePath, contentType: 'application/json' });
    await info.attach(`${name} screenshot`, { path: screenshotPath, contentType: 'image/png' });
}
