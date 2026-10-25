import { describe, expect, it } from 'vitest';
import { NAVIGATION_ITEMS, isNavigationItemActive } from './navigation';

describe('primary navigation', () => {
    it('contains only routes that exist in the app', () => {
        expect(NAVIGATION_ITEMS.map((item) => item.href)).toEqual([
            '/',
            '/workspace',
            '/technical-observability',
            '/settings/llm',
            '/settings/search',
        ]);
    });

    it('matches nested paths without confusing sibling prefixes', () => {
        expect(isNavigationItemActive('/settings/llm/keys', '/settings/llm')).toBe(true);
        expect(isNavigationItemActive('/settings/llm-tools', '/settings/llm')).toBe(false);
        expect(isNavigationItemActive('/workspace', '/')).toBe(false);
        expect(isNavigationItemActive('/', '/')).toBe(true);
    });
});
