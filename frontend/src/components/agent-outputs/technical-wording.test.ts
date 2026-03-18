import { describe, expect, it } from 'vitest';

import {
    buildMomentumSummaryLine,
    describeIndicatorHighlight,
    getMarketStatusDescriptor,
    resolveFdDescriptor,
    resolveMacdTone,
    resolveRsiDescriptor,
} from './technical-wording';

describe('technical wording', () => {
    it('describes MACD above signal but still below zero without saying positive', () => {
        const descriptor = resolveMacdTone(-6.503, -6.901);

        expect(descriptor.tone).toBe('warning');
        expect(descriptor.label).toBe('Above Signal');
        expect(descriptor.meaning).toContain('below zero');
        expect(descriptor.tacticalReadout).toBe('Early Improvement, Avoid Chasing');
    });

    it('keeps actionable market readouts while avoiding execution instructions', () => {
        const descriptor = getMarketStatusDescriptor(2.4);

        expect(descriptor.readoutLabel).toBe('Tactical Readout');
        expect(descriptor.readout).toBe('Do Not Chase');
        expect(descriptor.status).toBe('Extreme Overheating');
    });

    it('humanizes known indicator highlight names and states', () => {
        expect(describeIndicatorHighlight('ADX_14', 'NEUTRAL')).toEqual({
            displayName: 'Trend Strength',
            stateLabel: 'Trend Not Strong',
        });
        expect(describeIndicatorHighlight('FD_OPTIMAL_D', 'NEUTRAL')).toEqual({
            displayName: 'Series Memory',
            stateLabel: 'Persistent Structure',
        });
    });

    it('builds actionable RSI and FD descriptors for compact cards', () => {
        const rsi = resolveRsiDescriptor(28.4);
        const fd = resolveFdDescriptor(-2.12);

        expect(rsi.label).toBe('Oversold');
        expect(rsi.tacticalReadout).toBe('Watch for Rebound');
        expect(fd.label).toBe('Downside Stretch');
        expect(fd.tacticalReadout).toBe('Potential Rebound Zone');
    });

    it('builds a humanized momentum summary line', () => {
        const summary = buildMomentumSummaryLine({
            macd: resolveMacdTone(-6.503, -6.901),
            rsi: resolveRsiDescriptor(42.1),
            fd: resolveFdDescriptor(-0.127),
            rsiValue: 42.1,
            fdValue: -0.127,
        });

        expect(summary).toBe(
            'MACD is above signal · FD Z-score is near normal (-0.127) · RSI is in bearish bias (42.100)'
        );
    });
});
