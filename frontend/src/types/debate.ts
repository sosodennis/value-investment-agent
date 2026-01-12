export type Direction = 'LONG' | 'SHORT' | 'NEUTRAL';

export type PriceImplication = 'SURGE' | 'MODERATE_UP' | 'FLAT' | 'MODERATE_DOWN' | 'CRASH';

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
    final_verdict: Direction;
    kelly_confidence: number;
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
