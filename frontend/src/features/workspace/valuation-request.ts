import type { components } from '@/types/generated/api-contract';

type ValuationRequest = NonNullable<components['schemas']['RunRequest']['valuation_request']>;

export function buildAutomaticValuationRequest(manualOverride?: Record<string, unknown>) {
    return {
        contract_version: 'fundamental.v1',
        assumptions: {},
        uncertainty: { mode: 'monte_carlo' },
        ...(manualOverride ? { manual_override: manualOverride } : {}),
    } satisfies ValuationRequest;
}
