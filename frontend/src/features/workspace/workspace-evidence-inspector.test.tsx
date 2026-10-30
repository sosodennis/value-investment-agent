import { describe, expect, it } from 'vitest';
import { adaptAgentOutput } from '@/types/agents/output-adapter';
import type { AgentInfo, StandardAgentOutput } from '@/types/agents';
import { buildEvidenceItems } from './workspace-evidence-inspector';

const agent: AgentInfo = {
    id: 'fundamental_analysis',
    name: 'Fundamental Analyst',
    description: 'Fundamental analysis',
    avatar: 'FA',
    status: 'done',
};

describe('buildEvidenceItems', () => {
    it('falls back to the fiscal year and period when period_end_date is absent', () => {
        const output: StandardAgentOutput = {
            kind: 'fundamental_analysis.output',
            version: 'v1',
            summary: 'AAPL report',
            preview: {
                financial_reports: [{
                    base: {
                        fiscal_year: { value: 2025 },
                        fiscal_period: { value: 'FY' },
                        period_end_date: null,
                        currency: null,
                        company_name: null,
                        cik: null,
                        sic_code: null,
                        shares_outstanding: null,
                        total_revenue: { value: 416160000000, provenance: { concept: 'us-gaap:Revenue' } },
                        net_income: null,
                        income_tax_expense: null,
                        total_assets: null,
                        total_liabilities: null,
                        total_equity: null,
                        cash_and_equivalents: null,
                        operating_cash_flow: null,
                    },
                    extension_type: null,
                    extension: null,
                }],
            },
        };

        const items = buildEvidenceItems(agent, adaptAgentOutput(agent.id, output));
        const revenue = items.find((item) => item.title === 'Financial report · Total Revenue');

        expect(revenue?.period).toBe('2025 (FY)');
        expect(revenue?.source).toBe('SEC XBRL concept us-gaap:Revenue');
    });
});
