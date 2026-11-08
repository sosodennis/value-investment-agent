import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type {
    FundamentalCanonicalFact,
    FundamentalFactsReadResult,
} from '@/types/agents/fundamental-service-facts';
import { FinancialTable } from './FinancialTable';

afterEach(() => {
    cleanup();
});

const source = {
    source_url: 'https://www.sec.gov/Archives/filing.xml',
    source_hash: 'a'.repeat(64),
    source_role: 'filing' as const,
    captured_at: '2026-01-02T03:04:05Z',
    available_at: '2026-01-02T03:05:00Z',
    filed_at: '2026-01-01T00:00:00Z',
    accession_number: '0000000000-26-000001',
    parser_version: 'arelle-2.38.0',
    taxonomy_manifest_digest: 'b'.repeat(64),
    mapping_version: 'mapping-v3',
};

const context = {
    concept_qname: 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
    period_type: 'duration' as const,
    start_date: '2025-01-01',
    end_date: '2025-12-31',
    unit_qname: 'iso4217:USD',
    measure: 'iso4217:USD',
    dimensions: [],
    entity_scope: 'consolidated',
    consolidation_scope: 'consolidated',
    context_id: 'ctx-1',
};

function fact(overrides: Partial<FundamentalCanonicalFact>): FundamentalCanonicalFact {
    return {
        contract_version: 'fundamental.v1',
        fact_id: 'fact-revenue',
        issuer_id: 'issuer-1',
        concept: 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
        normalized_field: 'revenue',
        value: { kind: 'numeric', raw: '12500', numeric: 12500 },
        unit: 'USD',
        scale: 3,
        currency: 'USD',
        period: { kind: 'duration', start: '2025-01-01', end: '2025-12-31' },
        context,
        as_of: '2025-12-31T00:00:00Z',
        available_at: source.available_at,
        captured_at: source.captured_at,
        filed_at: source.filed_at,
        accession_number: source.accession_number,
        filing_version: 'filing-v1',
        is_amendment: false,
        taxonomy_version: 'us-gaap-2025',
        source,
        quality: 'verified',
        issue_codes: [],
        rejected_candidates: [],
        mapping_decision_id: 'mapping-1',
        mapping_confidence: 'high',
        ...overrides,
    };
}

const facts: FundamentalFactsReadResult = {
    contract_version: 'fundamental.v1',
    snapshot_id: 'snapshot-1',
    data_release_manifest_digest: 'd'.repeat(64),
    snapshot_manifest_digest: 'c'.repeat(64),
    identity: {
        issuer_id: 'issuer-1',
        issuer_name: 'Example Bank',
        domicile: 'US',
        reporting_basis: 'us-gaap',
        security_id: 'security-1',
        share_class: 'common',
        currency: 'USD',
        family: 'bank',
    },
    valuation_timestamp: '2026-01-03T00:00:00Z',
    quality_status: 'verified',
    issue_codes: [],
    facts: [
        fact({ fact_id: 'fact-revenue', normalized_field: 'revenue' }),
        fact({
            fact_id: 'fact-quarter',
            normalized_field: 'quarterly_revenue',
            value: { kind: 'numeric', raw: '8.25', numeric: 8.25 },
            unit: 'EUR',
            currency: 'EUR',
            scale: 0,
            period: { kind: 'duration', start: '2025-07-01', end: '2025-09-30' },
        }),
        fact({
            fact_id: 'fact-loss',
            normalized_field: 'loss',
            value: { kind: 'numeric', raw: '-42', numeric: -42 },
            unit: 'USD',
            scale: 0,
            period: { kind: 'instant', end: '2025-12-31', instant: '2025-12-31' },
        }),
        fact({
            fact_id: 'fact-zero',
            normalized_field: 'zero_balance',
            value: { kind: 'numeric', raw: '0', numeric: 0 },
            unit: 'shares',
            currency: undefined,
            scale: 0,
        }),
        fact({
            fact_id: 'fact-missing',
            normalized_field: 'capital_ratio',
            value: { kind: 'missing', status: 'missing', reason: 'No filed fact selected.' },
            unit: 'ratio',
            currency: undefined,
            scale: 0,
            quality: 'degraded',
            issue_codes: ['FACT_UNRESOLVED'],
        }),
        fact({
            fact_id: 'fact-not-applicable',
            normalized_field: 'dividend',
            value: { kind: 'missing', status: 'not_applicable', reason: 'Not applicable to this model.' },
            unit: 'USD',
            scale: 0,
            quality: 'provisional',
        }),
        fact({
            fact_id: 'fact-abstain',
            normalized_field: 'book_value',
            value: { kind: 'missing', status: 'unresolved', reason: 'Candidate facts conflict.' },
            unit: 'USD',
            scale: 0,
            quality: 'abstain',
        }),
    ],
};

describe('FinancialTable', () => {
    it('renders an explicit status when the service snapshot has no selectable facts', () => {
        render(<FinancialTable facts={{ ...facts, facts: [] }} />);

        screen.getByRole('status');
        screen.getByText('No canonical facts available');
        screen.getByText(/snapshot-1/);
        expect(screen.queryByRole('table')).toBeNull();
    });

    it('renders typed family, period, units, numeric states, and quality metadata', () => {
        render(<FinancialTable facts={facts} />);

        screen.getByText('Example Bank');
        screen.getByText(/Canonical facts selected from the immutable snapshot-1 snapshot/);
        screen.getByText(/Data release:/);
        screen.getByText('d'.repeat(64));
        expect(screen.getAllByRole('columnheader').every((header) => header.getAttribute('scope') === 'col')).toBe(true);
        expect(screen.getAllByLabelText('Quality: verified')).toHaveLength(4);
        screen.getByText(/Bank · us-gaap · USD · 7 selected facts/);
        screen.getByText('12,500');
        screen.getByText('8.25');
        screen.getByText('-42');
        screen.getByText('0');
        screen.getByText(/Unavailable · missing: No filed fact selected\./);
        screen.getByText(/Unavailable · not_applicable: Not applicable to this model\./);
        screen.getByText(/Unavailable · unresolved: Candidate facts conflict\./);
        expect(screen.getAllByText('2025-01-01 → 2025-12-31').length).toBeGreaterThan(0);
        screen.getByText('Instant · 2025-12-31');
        screen.getByText('2025-07-01 → 2025-09-30');
        screen.getByText('FACT_UNRESOLVED');
        const rowText = screen.getAllByRole('row').map((row) => row.textContent ?? '');
        expect(rowText.findIndex((row) => row.includes('fact-revenue'))).toBeLessThan(
            rowText.findIndex((row) => row.includes('fact-quarter'))
        );
    });

    it('renders canonical base-unit values without applying source scale twice', () => {
        render(
            <FinancialTable
                facts={{
                    ...facts,
                    facts: [fact({
                        fact_id: 'fact-live-revenue',
                        normalized_field: 'reported_revenue',
                        value: {
                            kind: 'numeric',
                            raw: '245122000000',
                            numeric: 245122000000,
                        },
                        scale: 6,
                    })],
                }}
            />
        );

        screen.getByText('245,122,000,000');
        expect(screen.queryByText('245,122,000,000,000,000')).toBeNull();
    });

    it('surfaces non-verified snapshot quality and issue codes', () => {
        render(
            <FinancialTable
                facts={{
                    ...facts,
                    quality_status: 'degraded',
                    issue_codes: ['SNAPSHOT_PARTIAL'],
                }}
            />
        );

        screen.getByRole('status');
        screen.getByText('Facts quality: degraded');
        screen.getByText('Issues: SNAPSHOT_PARTIAL');
    });

    it.each([
        ['bank', 'Bank'],
        ['industrial', 'Industrial'],
        ['reit', 'REIT'],
    ] as const)('uses the typed %s family metadata', (family, label) => {
        render(
            <FinancialTable
                facts={{ ...facts, identity: { ...facts.identity, family } }}
            />
        );

        screen.getByText(new RegExp(`${label} · us-gaap`));
    });

    it('pins the selected fact to the evidence inspector contract', () => {
        const onSelectEvidence = vi.fn();
        render(<FinancialTable facts={facts} onSelectEvidence={onSelectEvidence} />);

        fireEvent.click(screen.getByRole('button', { name: 'Inspect Revenue evidence' }));

        expect(onSelectEvidence).toHaveBeenCalledWith(expect.objectContaining({
            id: 'fundamental:service-fact:fact-revenue',
            factId: 'fact-revenue',
            concept: 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
            accessionNumber: '0000000000-26-000001',
            parserVersion: 'arelle-2.38.0',
            taxonomyVersion: 'us-gaap-2025',
            taxonomyManifestDigest: 'b'.repeat(64),
            mappingVersion: 'mapping-v3',
            sourceHash: 'a'.repeat(64),
            snapshotId: 'snapshot-1',
            snapshotManifestDigest: 'c'.repeat(64),
            unit: 'USD',
            scale: 3,
            issueCodes: [],
        }));
    });
});
