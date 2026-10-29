import { afterEach, describe, expect, it, vi } from 'vitest';

describe('Next.js API proxy configuration', () => {
    afterEach(() => {
        vi.unstubAllEnvs();
        vi.resetModules();
    });

    it('forwards versioned API routes to the configured internal backend', async () => {
        vi.stubEnv('BACKEND_INTERNAL_URL', 'http://backend:8000/');
        const { default: config } = await import('./next.config');

        const rewrites = await config.rewrites?.();

        expect(rewrites).toEqual([
            {
                source: '/api/v1/:path*',
                destination: 'http://backend:8000/api/v1/:path*',
            },
        ]);
    });
});
