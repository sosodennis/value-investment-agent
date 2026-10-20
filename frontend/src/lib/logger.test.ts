import { afterEach, describe, expect, it, vi } from 'vitest';
import { clientLogger } from './logger';

describe('clientLogger', () => {
    afterEach(() => {
        vi.unstubAllEnvs();
        vi.restoreAllMocks();
    });

    it('emits structured errors and redacts sensitive fields', () => {
        const error = vi.spyOn(console, 'error').mockImplementation(() => {});

        clientLogger.error('artifact.fetch.error', {
            artifact_id: 'artifact-1',
            access_token: 'secret-value',
        });

        const record = JSON.parse(String(error.mock.calls[0]?.[0])) as {
            event: string;
            fields: Record<string, unknown>;
            level: string;
            service: string;
        };
        expect(record.event).toBe('artifact.fetch.error');
        expect(record.level).toBe('ERROR');
        expect(record.service).toBe('frontend');
        expect(record.fields.artifact_id).toBe('artifact-1');
        expect(record.fields.access_token).toBe('[REDACTED]');
    });

    it('emits debug records only when explicitly enabled', () => {
        const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});
        vi.stubEnv('NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_LOGS', 'false');
        clientLogger.debug('artifact.fetch.start');
        expect(debug).not.toHaveBeenCalled();

        vi.stubEnv('NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_LOGS', 'true');
        clientLogger.debug('artifact.fetch.start');
        expect(debug).toHaveBeenCalledOnce();
    });
});
