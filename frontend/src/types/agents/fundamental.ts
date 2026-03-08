export interface Provenance {
    concept?: string;
    expression?: string;
    description?: string;
}

export interface TraceableField {
    value: string | number | null;
    provenance?: Provenance | null;
    timestamp?: string;
}

export interface FinancialReportBase {
    fiscal_year: TraceableField | null;
    fiscal_period: TraceableField | null;
    period_end_date: TraceableField | null;
    currency: TraceableField | null;
    company_name: TraceableField | null;
    cik: TraceableField | null;
    sic_code: TraceableField | null;
    shares_outstanding: TraceableField | null;

    total_revenue: TraceableField | null;
    net_income: TraceableField | null;
    income_tax_expense: TraceableField | null;
    total_assets: TraceableField | null;
    total_liabilities: TraceableField | null;
    total_equity: TraceableField | null;
    cash_and_equivalents: TraceableField | null;
    operating_cash_flow: TraceableField | null;
}

export interface IndustrialExtension {
    inventory: TraceableField | null;
    accounts_receivable: TraceableField | null;
    cogs: TraceableField | null;
    rd_expense: TraceableField | null;
    sga_expense: TraceableField | null;
    capex: TraceableField | null;
}

export interface FinancialServicesExtension {
    loans_and_leases: TraceableField | null;
    deposits: TraceableField | null;
    allowance_for_credit_losses: TraceableField | null;
    interest_income: TraceableField | null;
    interest_expense: TraceableField | null;
    provision_for_loan_losses: TraceableField | null;
}

export interface RealEstateExtension {
    real_estate_assets: TraceableField | null;
    accumulated_depreciation: TraceableField | null;
    depreciation_and_amortization: TraceableField | null;
    ffo: TraceableField | null;
}

export interface FinancialReport {
    base: FinancialReportBase;
    extension?: IndustrialExtension | FinancialServicesExtension | RealEstateExtension | null;
    extension_type?: 'Industrial' | 'FinancialServices' | 'RealEstate' | null;
}

export interface ForwardSignalEvidence {
    preview_text: string;
    full_text: string;
    source_url: string;
    doc_type?: string;
    period?: string;
    filing_date?: string;
    accession_number?: string;
    focus_strategy?: string;
    rule?: string;
    value_basis_points?: number;
    source_locator?: {
        text_scope: 'metric_text';
        char_start: number;
        char_end: number;
    };
}

export interface ForwardSignal {
    signal_id: string;
    source_type: string;
    metric: string;
    direction: 'up' | 'down' | 'neutral';
    value: number;
    unit: 'basis_points' | 'ratio';
    confidence: number;
    as_of: string;
    median_filing_age_days?: number;
    evidence: ForwardSignalEvidence[];
}

export interface FundamentalValuationDiagnostics {
    growth_rates_converged?: number[];
    terminal_growth_effective?: number;
    growth_consensus_policy?: string;
    growth_consensus_horizon?: string;
    terminal_anchor_policy?: string;
    terminal_anchor_stale_fallback?: boolean;
    base_growth_guardrail_applied?: boolean;
    base_growth_guardrail_version?: string;
    base_growth_raw_year1?: number;
    base_growth_raw_yearN?: number;
    base_growth_guarded_year1?: number;
    base_growth_guarded_yearN?: number;
    base_margin_guardrail_applied?: boolean;
    base_margin_guardrail_version?: string;
    base_margin_raw_year1?: number;
    base_margin_raw_yearN?: number;
    base_margin_guarded_year1?: number;
    base_margin_guarded_yearN?: number;
    forward_signal_mapping_version?: string;
    forward_signal_calibration_applied?: boolean;
    sensitivity_summary?: {
        enabled?: boolean;
        scenario_count?: number;
        max_upside_delta_pct?: number;
        max_downside_delta_pct?: number;
        top_drivers?: Array<{
            shock_dimension?: string;
            shock_value_bp?: number;
            delta_pct_vs_base?: number;
        }>;
    };
}

export interface FundamentalAnalysisSuccess {
    ticker: string;
    model_type: string;
    company_name: string;
    sector: string;
    industry: string;
    reasoning: string;
    financial_reports: FinancialReport[];
    forward_signals?: ForwardSignal[];
    valuation_diagnostics?: FundamentalValuationDiagnostics;
    status: 'done';
}

export interface FundamentalAnalysisError {
    message: string;
}

export type FundamentalAnalysisResult = FundamentalAnalysisSuccess | FundamentalAnalysisError;
