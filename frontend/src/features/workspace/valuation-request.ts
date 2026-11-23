import type { components } from '@/types/generated/api-contract';
import type { FundamentalRevision } from './outputs/fundamental-analysis/valuation-revision';

type ValuationRequest = NonNullable<components['schemas']['RunRequest']['valuation_request']>;

export function buildAutomaticValuationRequest() {
    return {
        contract_version: 'fundamental.v1',
        assumptions: {},
        uncertainty: { mode: 'monte_carlo' },
    } satisfies ValuationRequest;
}

export function buildFundamentalRevisionRequest(revision: FundamentalRevision) {
    return { contract_version: 'fundamental.v1', revision } satisfies ValuationRequest;
}
