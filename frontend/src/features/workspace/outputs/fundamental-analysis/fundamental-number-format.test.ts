import { describe, expect, it } from 'vitest';
import { assumptionNumberSemantic, factNumberSemantic, formatReportDatum, formatReportNumber, formatReportSeries, nodeNumberSemantic, type NumberSemantic } from './fundamental-number-format';

const perShare: NumberSemantic = { kind: 'per-share', currency: 'USD' };
const money: NumberSemantic = { kind: 'money', currency: 'USD' };
const ratio: NumberSemantic = { kind: 'ratio' };

describe('Fundamental number presentation', () => {
    it.each([
        ['229.88242539685962775556419207139754074672901162460', perShare, 'USD 229.88 / share'],
        ['144.665049', perShare, 'USD 144.67 / share'],
        ['173.100589', perShare, 'USD 173.10 / share'],
        ['197.999837', perShare, 'USD 198.00 / share'],
        ['1.005', perShare, 'USD 1.01 / share'],
        ['-1.005', perShare, 'USD −1.01 / share'],
        ['-0.000000004', perShare, 'USD −4.00e−9 / share'],
        ['0.00001234', perShare, 'USD 0.000012 / share'],
        ['0.000000004', ratio, '4.00e−7%'],
        ['0.0492', ratio, '4.92%'],
        ['.40', ratio, '40.00%'],
        ['0', ratio, '0.00%'],
        ['-0.000', ratio, '0.00%'],
        ['1.25', ratio, '125.00%'],
        ['331839000000', money, 'USD 331.84B'],
        ['999995000', money, 'USD 1.00B'],
        ['999995000000', money, 'USD 1.00T'],
        ['1000000000000000000000000', money, 'USD 1.00e+24'],
        ['-999.995', money, 'USD −1,000.00'],
        ['1e100000000000000000000', money, 'USD 1.00e+100000000000000000000'],
        ['1e-100000000000000000000', money, 'USD 1.00e−100000000000000000000'],
    ] satisfies [string, NumberSemantic, string][])('formats %s without a floating-point round trip', (raw, semantic, expected) => {
        expect(formatReportNumber(raw, semantic)).toBe(expected);
    });
    it('uses semantics rather than magnitude or labels', () => {
        expect(formatReportNumber('0.6', { kind: 'beta' })).toBe('0.60');
        expect(formatReportNumber('7532000000', { kind: 'shares' })).toBe('7.53B shares');
        expect(formatReportNumber('1.25', { kind: 'shares' })).toBe('1.25 shares');
        expect(formatReportNumber('1000000', { kind: 'count' })).toBe('1,000,000');
        expect(formatReportNumber('1000000000000000', { kind: 'count' })).toBe('1,000,000,000,000,000');
        expect(formatReportNumber('2026', { kind: 'year' })).toBe('FY2026');
        expect(formatReportNumber('-0.0242', { kind: 'percentage-points' })).toBe('−2.42 percentage points');
        expect(formatReportNumber('-0.0242', { kind: 'basis-points' })).toBe('−242.00 bps');
        expect(assumptionNumberSemantic('assumptions.wacc.beta', 'USD')).toEqual({ kind: 'beta' });
        expect(assumptionNumberSemantic('assumptions.forecast.reinvestment_rate[4]', 'USD')).toEqual(ratio);
        expect(factNumberSemantic('revenue', 'USD', 'iso4217:USD')).toEqual(money);
        expect(nodeNumberSemantic('per_share_value', 'currency/share', 'USD')).toEqual(perShare);
        expect(formatReportNumber('0.6', assumptionNumberSemantic('unknown.growth', 'USD'))).toBe('0.6 · Format not defined');
    });
    it('keeps a common table unit and extends the whole series precision for small nonzero values', () => {
        const series = formatReportSeries(['331839000000', '30000'], money);
        expect(series.values).toEqual(['331.839000', '0.000030']);
        expect(series.precision).toBe(6);
        expect(formatReportSeries(['1e24', '0.000000004'], money).values).toEqual(['1.00e+15', '4.00e−18']);
    });
    it('distinguishes unavailable variants and keeps zero as a number', () => {
        expect(formatReportDatum({ kind: 'unavailable', status: 'missing', reason: 'No filing.' })).toBe('Missing · No filing.');
        expect(formatReportDatum({ kind: 'unavailable', status: 'not_applicable', reason: 'No instrument.' })).toBe('Not applicable · No instrument.');
        expect(formatReportDatum({ kind: 'unavailable', status: 'unresolved', reason: 'Mapping pending.' })).toBe('Unavailable · Mapping pending.');
        expect(formatReportDatum({ kind: 'number', raw: '0', semantic: ratio })).toBe('0.00%');
    });
    it.each(['NaN', 'Infinity', '', ' ', '.'])('rejects malformed Decimal text %s', (raw) => {
        expect(() => formatReportNumber(raw, money)).toThrow(TypeError);
    });
});
