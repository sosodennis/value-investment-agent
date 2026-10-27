import { afterEach, describe, expect, it } from 'vitest';
import { csrfHeaders } from './auth-api';

describe('CSRF cookie parsing', () => {
    afterEach(() => {
        document.cookie = 'app_csrf=; Max-Age=0; path=/';
    });

    it('returns the CSRF header for a valid cookie', () => {
        document.cookie = 'app_csrf=csrf-token; path=/';

        expect(csrfHeaders()).toEqual({ 'X-CSRF-Token': 'csrf-token' });
    });

    it('ignores a malformed cookie instead of aborting the request setup', () => {
        document.cookie = 'app_csrf=%; path=/';

        expect(csrfHeaders()).toEqual({});
    });

    it('ignores decoded values that are unsafe as request header content', () => {
        document.cookie = 'app_csrf=%0A; path=/';

        expect(csrfHeaders()).toEqual({});
    });
});
