export type Direction = 'LONG' | 'SHORT' | 'NEUTRAL';

export interface DebateConclusion {
    winning_thesis: string;
    primary_catalyst: string;
    primary_risk: string;
    confidence_score: number;
    direction: Direction;
    supporting_factors: string[];
    debate_rounds: number;
}

export interface DebateAgentOutput {
    conclusion: DebateConclusion | null;
    history?: any[];
    bull_thesis?: string;
    bear_thesis?: string;
}
