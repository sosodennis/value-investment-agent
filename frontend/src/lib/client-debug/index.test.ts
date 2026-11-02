import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
});

describe('debugCapture', () => {
    it('is a no-op when capture is disabled', async () => {
        vi.stubEnv('NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE', 'false');
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);

        const { debugCapture } = await import('./index');
        debugCapture.emit('ui.layout', { rect: { width: 10 } });
        await debugCapture.flush();

        expect(debugCapture.isEnabled).toBe(false);
        expect(debugCapture.captureId).toBeNull();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('batches a sanitized event with browser context', async () => {
        vi.stubEnv('NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE', 'true');
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
        vi.stubGlobal('fetch', fetchMock);
        document.cookie = 'app_csrf=csrf-token; path=/';
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
        Object.defineProperty(window, 'innerHeight', { configurable: true, value: 900 });
        Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 2 });
        Object.defineProperty(window, 'scrollX', { configurable: true, value: 12 });
        Object.defineProperty(window, 'scrollY', { configurable: true, value: 24 });
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            value: () => ({ matches: false }),
        });

        const { debugCapture } = await import('./index');
        debugCapture.emit(
            'ui.layout',
            {
                rect: { width: 10, height: 20 },
                access_token: 'secret',
            },
            { component: 'WorkspaceOutputPanel' },
        );
        await debugCapture.flush();

        expect(fetchMock).toHaveBeenCalledOnce();
        const [path, init] = fetchMock.mock.calls[0] ?? [];
        expect(path).toBe('/api/v1/client-debug/events');
        const body: unknown = JSON.parse(String(init?.body));
        expect(body).toEqual({
            capture_id: expect.any(String),
            events: [
                expect.objectContaining({
                    component: 'WorkspaceOutputPanel',
                    context: expect.objectContaining({
                        viewport: { width: 1440, height: 900, dpr: 2 },
                    }),
                    details: expect.objectContaining({
                        access_token: '[REDACTED]',
                    }),
                }),
            ],
            schema_version: 'client_debug.v1',
        });
        const headers = init?.headers;
        if (!(headers instanceof Headers)) {
            throw new Error('debug capture should send Headers');
        }
        expect(headers.get('X-CSRF-Token')).toBe('csrf-token');
    });

    it('redacts URLs, query strings, and JWT values under generic keys', async () => {
        vi.stubEnv('NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE', 'true');
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
        vi.stubGlobal('fetch', fetchMock);
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            value: () => ({ matches: false }),
        });

        const { debugCapture } = await import('./index');
        debugCapture.emit('error.state', {
            metadata: 'https://example.test/path?email=private@example.test',
            query: '?sessionId=private-session-123456',
            tokenLike: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signaturevalue123',
        });
        await debugCapture.flush();

        const [, init] = fetchMock.mock.calls[0] ?? [];
        const body: unknown = JSON.parse(String(init?.body));
        expect(body).toMatchObject({
            events: [
                {
                    details: {
                        metadata: '[REDACTED]',
                        tokenLike: '[REDACTED]',
                    },
                },
            ],
        });
        expect(body).toMatchObject({
            events: [{ details: expect.not.objectContaining({ query: expect.anything() }) }],
        });
    });

    it('requeues events after a failed transport without throwing from emit', async () => {
        vi.stubEnv('NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE', 'true');
        const fetchMock = vi
            .fn()
            .mockResolvedValueOnce(new Response(null, { status: 503 }))
            .mockResolvedValueOnce(new Response(null, { status: 202 }));
        vi.stubGlobal('fetch', fetchMock);
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            value: () => ({ matches: false }),
        });

        const { debugCapture } = await import('./index');
        debugCapture.emit('interaction.click', { target: 'model-picker' });
        await debugCapture.flush();
        await debugCapture.flush();

        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('drops a permanent transport failure instead of retrying forever', async () => {
        vi.stubEnv('NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE', 'true');
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
        vi.stubGlobal('fetch', fetchMock);
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            value: () => ({ matches: false }),
        });

        const { debugCapture } = await import('./index');
        debugCapture.emit('error.state', { code: 'capture-disabled' });
        await debugCapture.flush();
        await debugCapture.flush();

        expect(fetchMock).toHaveBeenCalledOnce();
    });

    it('sends one bounded idempotent keepalive batch when pagehide interrupts a request', async () => {
        vi.stubEnv('NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE', 'true');
        let resolveFirst: (() => void) | undefined;
        const firstResponse = new Promise<Response>((resolve) => {
            resolveFirst = () => resolve(new Response(null, { status: 202 }));
        });
        const fetchMock = vi.fn().mockReturnValueOnce(firstResponse).mockResolvedValueOnce(
            new Response(null, { status: 202 }),
        );
        vi.stubGlobal('fetch', fetchMock);
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            value: () => ({ matches: false }),
        });

        const { debugCapture } = await import('./index');
        debugCapture.emit('interaction.before', { target: 'model-picker' });
        const firstFlush = debugCapture.flush();
        debugCapture.emit('interaction.after', { target: 'model-picker' });
        window.dispatchEvent(new Event('pagehide'));
        resolveFirst?.();
        await firstFlush;
        await new Promise((resolve) => setTimeout(resolve, 0));

        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(fetchMock.mock.calls[1]?.[1]?.keepalive).toBe(true);
        const terminalBody: unknown = JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body));
        expect(terminalBody).toMatchObject({ events: [{ name: 'interaction.before' }, { name: 'interaction.after' }] });
    });
});
