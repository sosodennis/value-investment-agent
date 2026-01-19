/**
 * Technical Analysis Frontend Types
 */

// Mirrors the backend Pydantic models in technical_analysis/structures.py

export enum MemoryStrength {
    STRUCTURALLY_STABLE = "structurally_stable",
    BALANCED = "balanced",
    FRAGILE = "fragile"
}

export enum StatisticalState {
    EQUILIBRIUM = "equilibrium",
    DEVIATING = "deviating",
    STATISTICAL_ANOMALY = "anomaly"
}

export enum RiskLevel {
    LOW = "low",
    MEDIUM = "medium",
    CRITICAL = "critical"
}

export interface FracDiffMetrics {
    optimal_d: number;
    window_length: number;
    adf_statistic: number;
    adf_pvalue: number;
    memory_strength: MemoryStrength;
}

export interface SignalState {
    z_score: number;
    statistical_state: StatisticalState;
    direction: string;
    risk_level: RiskLevel;
}

export interface TechnicalSignalOutput {
    ticker: string;
    timestamp: string;
    frac_diff_metrics: FracDiffMetrics;
    signal_state: SignalState;
    semantic_tags: string[];
    llm_interpretation?: string;
    raw_data?: {
        price_series?: Record<string, number>;
        fracdiff_series?: Record<string, number>;
    };
}
