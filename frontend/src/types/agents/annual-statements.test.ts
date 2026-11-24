import { describe, expect, it } from 'vitest';
import wire from '../../../../contracts/fixtures/annual-statements.v1.json';
import { parseAnnualStatements } from './annual-statements';

const fixture = () => structuredClone(wire);

describe('annual statement artifact boundary', () => {
    it('retains exact Decimal, actual periods, source context and missing reasons', () => {
        const parsed = parseAnnualStatements(fixture());
        const first = parsed.statements.tables[0]?.rows[0]?.cells[0];
        expect(first?.status).toBe('reported');
        if (first?.status !== 'reported') throw new Error('Expected reported fixture');
        expect(first.fact.value).toBe('9007199254740993.125');
        expect(first.fact.context.context_id).toBe('context-revenueFY2023');
        expect(parsed.statements.tables[0]?.columns[0]).toMatchObject({ duration_days: 371, calendar: '53_week' });
        expect(parsed.statements.tables[1]?.rows[1]?.cells[0]).toMatchObject({ status: 'unavailable', missing: { status: 'unresolved', reason: 'Original filing could not be parsed with the retained taxonomy.' } });
        expect(parsed.statements.profile.history_coverage_target).toBe(5);
    });

    it.each(['numeric-coercion', 'lookahead', 'wrong-issuer', 'wrong-period', 'missing-evidence', 'unknown-status', 'unknown-version'])('rejects %s', (change) => {
        const raw = fixture();
        const cell = raw.statements.tables[0]?.rows[0]?.cells[0];
        if (!cell || !('fact' in cell) || !cell.fact) throw new Error('Expected fixture cell');
        const mutations: Record<string, () => unknown> = {
            'numeric-coercion': () => Reflect.set(cell.fact, 'value', 42),
            lookahead: () => Reflect.set(cell.fact, 'available_at', '2025-01-01T00:00:00Z'),
            'wrong-issuer': () => Reflect.set(cell.fact, 'issuer_id', '0000000002'),
            'wrong-period': () => Reflect.set(cell, 'period_id', 'a'.repeat(64)),
            'missing-evidence': () => Reflect.set(raw.statements, 'candidate_evidence', []),
            'unknown-status': () => Reflect.set(cell, 'status', 'estimated'),
            'unknown-version': () => Reflect.set(raw, 'contract_version', 'fundamental.annual-statements.v2'),
        };
        mutations[change]?.();
        expect(() => parseAnnualStatements(raw)).toThrow(TypeError);
    });
});
