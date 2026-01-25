export type Direction = 'STRONG_LONG' | 'LONG' | 'NEUTRAL' | 'AVOID' | 'SHORT' | 'STRONG_SHORT';

export type PriceImplication = 'SURGE' | 'MODERATE_UP' | 'FLAT' | 'MODERATE_DOWN' | 'CRASH';

export type RiskProfileType = 'DEFENSIVE_VALUE' | 'GROWTH_TECH' | 'SPECULATIVE_CRYPTO_BIO';

export interface Scenario {
    probability: number;
    outcome_description: string;
    price_implication: PriceImplication;
}

export interface DebateConclusion {
    scenario_analysis: {
        bull_case: Scenario;
        bear_case: Scenario;
        base_case: Scenario;
    };
    // V2.0 Simplified Metrics
    rr_ratio?: number;
    alpha?: number;
    risk_free_benchmark?: number;
    raw_ev?: number;

    // V2.0 Metrics & State
    risk_profile: RiskProfileType;
    final_verdict: Direction;
    conviction?: number;
    analysis_bias?: string;
    model_summary?: string;
    data_quality_warning?: boolean;

    winning_thesis: string;
    primary_catalyst: string;
    primary_risk: string;
    supporting_factors: string[];
    debate_rounds: number;
}

// Updated to match backend artifact structure
// Backend sends the conclusion data directly, not nested
export interface DebateAgentOutput extends DebateConclusion {
    // Optional legacy fields
    history?: any[];
    bull_thesis?: string;
    bear_thesis?: string;
}
