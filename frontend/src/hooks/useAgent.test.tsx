import { renderHook } from '@testing-library/react';
import { useAgent } from './useAgent';
import { describe, it, expect } from 'vitest';

describe('useAgent Performance', () => {
    it('should have unstable sendMessage reference due to unmemoized parseStream', () => {
        const { result, rerender } = renderHook(() => useAgent('test-agent'));

        const firstSendMessage = result.current.sendMessage;

        // Force a re-render
        rerender();

        const secondSendMessage = result.current.sendMessage;

        // Optimization: The function reference SHOULD NOT change because parseStream is now memoized
        expect(secondSendMessage).toBe(firstSendMessage);
    });
});
