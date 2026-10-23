import { createRequire } from 'node:module';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const nextVersion = require(require.resolve('next/package.json')).version;

const repetitions = Number(process.env.REPETITIONS ?? '5');
const baseUrl = process.env.FRONTEND_URL ?? 'http://127.0.0.1:13100';
const backendUrl = process.env.SSE_BACKEND_URL ?? 'http://127.0.0.1:18100';
const eventIntervalMs = Number(process.env.PROBE_INTERVAL_MS ?? '100');
const browser = await chromium.launch({ headless: true });
try {
    const page = await browser.newPage();
    const probeUrl = new URL(baseUrl);
    probeUrl.searchParams.set('probe_interval_ms', String(eventIntervalMs));
    await page.goto(probeUrl.toString(), { waitUntil: 'networkidle' });
    const backendHealth = await fetch(`${backendUrl}/health`).then((response) => response.json());
    const expectedDeliveryCount = backendHealth.native_sse ? 9 : 6;
    const expectedReplayCount = backendHealth.native_sse ? 6 : 3;
    const minimumIncrementalGapMs = Math.max(20, eventIntervalMs * 0.4);
    const output = [];
    const failures = [];
    for (let repetition = 1; repetition <= repetitions; repetition += 1) {
        await page.context().addCookies([{
            name: 'probe_session',
            value: 'authenticated',
            url: baseUrl,
            sameSite: 'Lax',
        }]);
        const batch = await page.evaluate(async ({ expectedDeliveryCount, expectedReplayCount }) => {
            const button = [...document.querySelectorAll('button')].find((item) => item.textContent === 'Run probe');
            if (!button) throw new Error('probe button missing');
            button.click();
            const results = document.querySelector('#results');
            if (!results) throw new Error('results output missing');
            await new Promise((resolve, reject) => {
                const timeout = setTimeout(() => reject(new Error('probe timeout')), 30000);
                const observer = new MutationObserver(() => {
                    try {
                        const parsed = JSON.parse(results.textContent || '[]');
                        const replayOutput = document.querySelector('#replays');
                        const replayResults = JSON.parse(replayOutput?.textContent || '[]');
                        const authorizationOutput = document.querySelector('#authorization');
                        const authorizationResults = JSON.parse(authorizationOutput?.textContent || '[]');
                        if (parsed.length === expectedDeliveryCount && replayResults.length === expectedReplayCount && authorizationResults.length === 3) {
                            clearTimeout(timeout);
                            observer.disconnect();
                            resolve(parsed);
                        }
                    } catch {}
                });
                observer.observe(results, { childList: true, characterData: true, subtree: true });
                observer.observe(document.querySelector('#replays'), { childList: true, characterData: true, subtree: true });
                observer.observe(document.querySelector('#authorization'), { childList: true, characterData: true, subtree: true });
            });
            return {
                delivery: JSON.parse(results.textContent || '[]'),
                replay: JSON.parse(document.querySelector('#replays')?.textContent || '[]'),
                authorization: JSON.parse(document.querySelector('#authorization')?.textContent || '[]'),
            };
        }, { expectedDeliveryCount, expectedReplayCount });
        const deliveryChecks = batch.delivery.map((result) => ({
            route: result.route,
            ordered: result.ids.join(',') === '1,2,3,4,5,6',
            terminal: result.terminal,
            incremental: result.receivedAt.slice(1).every((time, index) => time - result.receivedAt[index] >= minimumIncrementalGapMs),
            firstEventMs: result.receivedAt[0] ?? null,
            eventGapsMs: result.receivedAt.slice(1).map((time, index) => Number((time - result.receivedAt[index]).toFixed(2))),
            minimumIncrementalGapMs,
            headers: result.headers,
        }));
        if (deliveryChecks.some((check) => !check.ordered || !check.terminal || !check.incremental)) {
            failures.push({ repetition, type: 'delivery', checks: deliveryChecks });
        }
        if (batch.replay.some((result) => !result.gapFree)) {
            failures.push({ repetition, type: 'replay', checks: batch.replay });
        }
        if (batch.authorization.some((result) => result.status !== 401)) {
            failures.push({ repetition, type: 'authorization', checks: batch.authorization });
        }
        output.push({ repetition, batch, deliveryChecks });
    }
    process.stdout.write(`${JSON.stringify({ baseUrl, backendUrl, nextVersion, backendHealth, eventIntervalMs, minimumIncrementalGapMs, repetitions, passed: failures.length === 0, failures, output }, null, 2)}\n`);
    if (failures.length > 0) process.exitCode = 1;
} finally {
    await browser.close();
}
