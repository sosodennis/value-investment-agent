export type Direction = 'LONG' | 'SHORT' | 'NEUTRAL';

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
    risk_profile: RiskProfileType;
    final_verdict: Direction;
    kelly_confidence: number;
    expected_value?: number;
    variance?: number;
    hurdle_rate?: number;  // CAPM-calculated threshold
    beta?: number;  // Stock's market volatility
    crash_impact?: number;  // VaR stress test value
    data_source?: string;  // "REAL_TIME" or "STATIC_FALLBACK"
    risk_override?: boolean;
    p_bull?: number;
    p_bear?: number;
    winning_thesis: string;
    primary_catalyst: string;
    primary_risk: string;
    supporting_factors: string[];
    debate_rounds: number;
}

export interface DebateAgentOutput {
    conclusion: DebateConclusion | null;
    history?: any[];
    bull_thesis?: string;
    bear_thesis?: string;
}
