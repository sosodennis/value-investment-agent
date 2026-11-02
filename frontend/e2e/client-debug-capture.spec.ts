import { execFileSync } from 'node:child_process';
import { rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const bundlePath = join(tmpdir(), `client-debug-capture-${process.pid}.js`);
type CapturedBatch = { capture_id: string; events: Array<Record<string, unknown>> };

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseBatch(value: unknown): CapturedBatch {
    if (!isRecord(value) || typeof value.capture_id !== 'string' || !Array.isArray(value.events)) {
        throw new Error('client debug helper emitted an invalid batch');
    }
    const events: Array<Record<string, unknown>> = [];
    for (const event of value.events) {
        if (!isRecord(event)) throw new Error('client debug helper emitted an invalid event');
        events.push(event);
    }
    return { capture_id: value.capture_id, events };
}

test.beforeAll(() => {
    execFileSync(
        resolve('node_modules/.bin/esbuild'),
        [
            'src/lib/client-debug/index.ts',
            '--bundle',
            '--platform=browser',
            '--format=iife',
            '--global-name=ClientDebugBundle',
            '--define:process.env.NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE="true"',
            '--footer:js=window.__clientDebugCapture=ClientDebugBundle.debugCapture;',
            `--outfile=${bundlePath}`,
        ],
    );
});

test.afterAll(() => {
    rmSync(bundlePath, { force: true });
});

test('captures browser layout, interaction, animation, and performance evidence on navigation', async ({ page }) => {
    const batches: Array<{ capture_id: string; events: Array<Record<string, unknown>> }> = [];

    await page.context().addCookies([
        {
            name: 'app_csrf',
            value: 'browser-test-csrf-token',
            url: 'http://127.0.0.1:43192',
        },
    ]);
    await page.route('**/api/v1/auth/me', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
                auth_type: 'session',
                email: 'debug-capture@example.test',
                role: 'user',
                subject: 'debug-capture-user',
                user_id: 'debug-capture-user',
                organization_id: 'debug-capture-organization',
                membership_id: 'debug-capture-membership',
            }),
        });
    });
    await page.route('**/api/v1/organizations**', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    await page.route('**/api/v1/client-debug/events', async (route) => {
        expect(route.request().method()).toBe('POST');
        expect(route.request().headers()['x-csrf-token']).toBe('browser-test-csrf-token');
        const payload = parseBatch(route.request().postDataJSON());
        batches.push(payload);
        await route.fulfill({
            status: 202,
            contentType: 'application/json',
            body: JSON.stringify({
                schema_version: 'client_debug.v1',
                capture_id: payload.capture_id,
                accepted: payload.events.length,
                duplicates: 0,
                dropped: 0,
                request_id: 'browser-debug-request',
            }),
        });
    });

    await page.goto('/login');
    await page.addScriptTag({ path: bundlePath });
    const captureRequest = page.waitForRequest((request) =>
        new URL(request.url()).pathname === '/api/v1/client-debug/events',
    );
    await page.evaluate(async () => {
        const debugCapture: unknown = Reflect.get(window, '__clientDebugCapture');
        if (typeof debugCapture !== 'object' || debugCapture === null) {
            throw new Error('client debug helper was not exposed by the test bundle');
        }
        const isEnabled = Reflect.get(debugCapture, 'isEnabled');
        const emit = Reflect.get(debugCapture, 'emit');
        const flush = Reflect.get(debugCapture, 'flush');
        if (isEnabled !== true || typeof emit !== 'function' || typeof flush !== 'function') {
            throw new Error('client debug helper is disabled or has no emit method');
        }

        for (const [name, details] of [
            ['ui.layout', { target: 'login-form', rect: { x: 10, y: 20, width: 320, height: 240 } }],
            ['interaction.click', { target: 'submit', pointer: { type: 'mouse', x: 170, y: 340 } }],
            ['animation.sample', { target: 'submit-feedback', phase: 'running', elapsedMs: 80, progress: 0.5 }],
            ['performance.measure', { name: 'login-render', durationMs: 18.2, startTimeMs: performance.now() }],
        ] as const) {
            Reflect.apply(emit, debugCapture, [name, details, { component: 'ClientDebugAcceptanceProbe' }]);
        }
        await Reflect.apply(flush, debugCapture, []);
    });

    await page.goto('/register');
    const request = await captureRequest;
    expect(request.method()).toBe('POST');

    expect(batches).toHaveLength(1);
    const payload = batches[0];
    expect(payload?.capture_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(payload?.events.map((event) => event.name)).toEqual([
        'ui.layout',
        'interaction.click',
        'animation.sample',
        'performance.measure',
    ]);
    expect(payload?.events[0]).toMatchObject({
        component: 'ClientDebugAcceptanceProbe',
        context: {
            route: '/login',
            viewport: { width: expect.any(Number), height: expect.any(Number) },
        },
    });
    expect(payload?.events[2]?.details).toMatchObject({ progress: 0.5 });
    expect(payload?.events[3]?.details).toMatchObject({ durationMs: 18.2 });
});
