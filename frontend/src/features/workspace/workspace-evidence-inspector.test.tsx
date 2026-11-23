import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { adaptAgentOutput } from '@/types/agents/output-adapter';
import type { AgentInfo, StandardAgentOutput } from '@/types/agents';
import { buildEvidenceItems, EvidenceInspector } from './workspace-evidence-inspector';

const agent: AgentInfo = {
    id: 'fundamental_analysis',
    name: 'Fundamental Analyst',
    description: 'Fundamental analysis',
    avatar: 'FA',
    status: 'done',
};

describe('buildEvidenceItems', () => {
    it('keeps unverified legacy preview financial values out of the Fundamental evidence inventory', () => {
        const output: StandardAgentOutput = {
            kind: 'fundamental_analysis.output', version: 'v1', summary: 'AAPL report',
            preview: { intrinsic_value: 123, distribution_summary: { mean: 456 } },
        };
        const items = buildEvidenceItems(agent, adaptAgentOutput(agent.id, output));
        expect(items.map((item) => item.title)).toEqual(['Fundamental Analyst summary']);
    });

    it('renders selected service fact provenance and marks absent metadata unavailable', () => {
        const item = {
            id: 'fundamental:service-fact:fact-1',
            title: 'Service fact · Revenue',
            value: '12,500',
            source: 'filing · https://www.sec.gov/Archives/filing.xml',
            period: '2025-01-01 → 2025-12-31',
            confidence: 'verified · mapping high',
            factId: 'fact-1',
            accessionNumber: '0000000000-26-000001',
            filedAt: '2026-01-01T00:00:00Z',
            availableAt: '2026-01-02T03:05:00Z',
            capturedAt: '2026-01-02T03:04:05Z',
            parserVersion: 'arelle-2.38.0',
            taxonomyVersion: 'us-gaap-2025',
            mappingVersion: 'mapping-v3',
            sourceHash: 'a'.repeat(64),
            snapshotId: 'snapshot-1',
            snapshotManifestDigest: 'b'.repeat(64),
            unit: 'USD',
            scale: 3,
            issueCodes: [],
        };

        render(<EvidenceInspector items={[item]} selected={item} onSelect={() => undefined} />);

        screen.getByText('fact-1');
        screen.getByText('0000000000-26-000001');
        screen.getByText('arelle-2.38.0');
        screen.getByText('snapshot-1');
        expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
        expect(screen.queryByText(/SEC XBRL concept/)).toBeNull();
    });
});
