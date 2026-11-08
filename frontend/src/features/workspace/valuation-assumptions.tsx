import { useEffect, useMemo, useState, type ChangeEvent, type ReactNode } from 'react';
import { CircleAlert } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';

type FieldKey =
    | 'baseRevenue'
    | 'revenueGrowth'
    | 'operatingMargin'
    | 'reinvestmentRate'
    | 'riskFreeRate'
    | 'beta'
    | 'equityRiskPremium'
    | 'preTaxCostOfDebt'
    | 'taxRate'
    | 'debtWeight'
    | 'equityWeight'
    | 'terminalGrowth'
    | 'cash'
    | 'debt'
    | 'preferredStock'
    | 'leaseLiabilities'
    | 'nonControllingInterest'
    | 'dilutedShares'
    | 'traceDescription';

type FormState = Record<FieldKey, string>;

export type CompactFundamentalValuationRequest = Record<string, unknown> & {
    contract_version: 'fundamental.v1';
    model_id: 'fcff_dcf';
    model_version: 'fcff_dcf-v1';
    policy_id: 'fcff_dcf-us-gaap-public-v1';
    assumptions: {
        forecast: {
            base_revenue?: string;
            revenue_growth: string[];
            operating_margin: string[];
            reinvestment_rate: string[];
        };
        wacc: {
            risk_free_rate: string;
            beta: string;
            equity_risk_premium: string;
            pre_tax_cost_of_debt: string;
            tax_rate: string;
            debt_weight: string;
            equity_weight: string;
        };
        terminal_growth: string;
        capital_bridge: {
            cash: string;
            debt: string;
            preferred_stock: string;
            lease_liabilities: string;
            non_controlling_interest: string;
            diluted_shares: string;
        };
        trace: { description: string };
    };
    uncertainty: { mode: 'none' };
};

const initialState: FormState = {
    baseRevenue: '',
    revenueGrowth: '',
    operatingMargin: '',
    reinvestmentRate: '',
    riskFreeRate: '',
    beta: '',
    equityRiskPremium: '',
    preTaxCostOfDebt: '',
    taxRate: '',
    debtWeight: '',
    equityWeight: '',
    terminalGrowth: '',
    cash: '',
    debt: '',
    preferredStock: '',
    leaseLiabilities: '',
    nonControllingInterest: '',
    dilutedShares: '',
    traceDescription: '',
};

const DECIMAL_PATTERN = /^-?(?:\d+(?:\.\d*)?|\.\d+)$/;

function parseDecimal(value: string, label: string): string {
    const normalized = value.trim();
    if (!normalized || !DECIMAL_PATTERN.test(normalized)) {
        throw new TypeError(`${label} must be a decimal value.`);
    }
    return normalized;
}

function parseDecimalList(value: string, label: string): string[] {
    const items = value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
    if (items.length === 0) throw new TypeError(`${label} requires one value.`);
    return items.map((item) => parseDecimal(item, label));
}

function decimalNumber(value: string, label: string): number {
    const parsed = Number(parseDecimal(value, label));
    if (!Number.isFinite(parsed)) throw new TypeError(`${label} must be finite.`);
    return parsed;
}

function buildRequest(state: FormState): CompactFundamentalValuationRequest {
    const debtWeight = decimalNumber(state.debtWeight, 'Debt weight');
    const equityWeight = decimalNumber(state.equityWeight, 'Equity weight');
    if (Math.abs(debtWeight + equityWeight - 1) > 1e-9) {
        throw new TypeError('Debt weight and equity weight must sum to 1.');
    }
    const traceDescription = state.traceDescription.trim();
    if (!traceDescription) throw new TypeError('Assumption trace is required.');
    if (decimalNumber(state.dilutedShares, 'Diluted shares') <= 0) {
        throw new TypeError('Diluted shares must be greater than 0.');
    }
    const baseRevenue = state.baseRevenue.trim();
    return {
        contract_version: 'fundamental.v1',
        model_id: 'fcff_dcf',
        model_version: 'fcff_dcf-v1',
        policy_id: 'fcff_dcf-us-gaap-public-v1',
        assumptions: {
            forecast: {
                ...(baseRevenue ? { base_revenue: parseDecimal(baseRevenue, 'Base revenue') } : {}),
                revenue_growth: parseDecimalList(state.revenueGrowth, 'Revenue growth'),
                operating_margin: parseDecimalList(state.operatingMargin, 'Operating margin'),
                reinvestment_rate: parseDecimalList(state.reinvestmentRate, 'Reinvestment rate'),
            },
            wacc: {
                risk_free_rate: parseDecimal(state.riskFreeRate, 'Risk-free rate'),
                beta: parseDecimal(state.beta, 'Beta'),
                equity_risk_premium: parseDecimal(state.equityRiskPremium, 'Equity risk premium'),
                pre_tax_cost_of_debt: parseDecimal(state.preTaxCostOfDebt, 'Pre-tax cost of debt'),
                tax_rate: parseDecimal(state.taxRate, 'Tax rate'),
                debt_weight: parseDecimal(state.debtWeight, 'Debt weight'),
                equity_weight: parseDecimal(state.equityWeight, 'Equity weight'),
            },
            terminal_growth: parseDecimal(state.terminalGrowth, 'Terminal growth'),
            capital_bridge: {
                cash: parseDecimal(state.cash, 'Cash'),
                debt: parseDecimal(state.debt, 'Debt'),
                preferred_stock: parseDecimal(state.preferredStock, 'Preferred stock'),
                lease_liabilities: parseDecimal(state.leaseLiabilities, 'Lease liabilities'),
                non_controlling_interest: parseDecimal(state.nonControllingInterest, 'Non-controlling interest'),
                diluted_shares: parseDecimal(state.dilutedShares, 'Diluted shares'),
            },
            trace: { description: traceDescription },
        },
        uncertainty: { mode: 'none' },
    };
}

export function ValuationAssumptionsEditor({
    disabled = false,
    onRequestChange,
}: {
    disabled?: boolean;
    onRequestChange: (request: CompactFundamentalValuationRequest | null) => void;
}) {
    const [state, setState] = useState<FormState>(initialState);
    const [touched, setTouched] = useState(false);
    const validation = useMemo(() => {
        try {
            return { request: buildRequest(state), error: null };
        } catch (reason) {
            const message = reason instanceof Error ? reason.message : 'Complete all valuation inputs.';
            return { request: null, error: message };
        }
    }, [state]);
    useEffect(() => {
        onRequestChange(validation.request);
    }, [onRequestChange, validation.request]);
    const error = validation.error;

    const update = (key: FieldKey) => (event: ChangeEvent<HTMLInputElement>) => {
        setTouched(true);
        setState((current) => ({ ...current, [key]: event.target.value }));
    };

    return (
        <fieldset disabled={disabled} className="mt-3 w-full border-t pt-3">
            <legend className="px-1 text-sm font-medium">Caller-owned valuation assumptions</legend>
            <p className="mt-1 text-xs text-muted-foreground">
                Enter decimal rates such as 0.08 for 8%. Values are sent to the Fundamental service and are never inferred from the ticker.
            </p>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
                <AssumptionGroup title="Forecast" description="Comma-separated values represent the forecast years.">
                    <DecimalField id="base-revenue" label="Base revenue (optional)" value={state.baseRevenue} onChange={update('baseRevenue')} />
                    <DecimalField id="revenue-growth" label="Revenue growth" value={state.revenueGrowth} onChange={update('revenueGrowth')} placeholder="0.05, 0.05, 0.04" />
                    <DecimalField id="operating-margin" label="Operating margin" value={state.operatingMargin} onChange={update('operatingMargin')} placeholder="0.15, 0.16, 0.17" />
                    <DecimalField id="reinvestment-rate" label="Reinvestment rate" value={state.reinvestmentRate} onChange={update('reinvestmentRate')} placeholder="0.20, 0.18, 0.16" />
                </AssumptionGroup>
                <AssumptionGroup title="WACC" description="Weights must add up to 1.">
                    <DecimalField id="risk-free-rate" label="Risk-free rate" value={state.riskFreeRate} onChange={update('riskFreeRate')} />
                    <DecimalField id="beta" label="Beta" value={state.beta} onChange={update('beta')} />
                    <DecimalField id="equity-risk-premium" label="Equity risk premium" value={state.equityRiskPremium} onChange={update('equityRiskPremium')} />
                    <DecimalField id="pre-tax-cost-of-debt" label="Pre-tax cost of debt" value={state.preTaxCostOfDebt} onChange={update('preTaxCostOfDebt')} />
                    <DecimalField id="tax-rate" label="Tax rate" value={state.taxRate} onChange={update('taxRate')} />
                    <DecimalField id="debt-weight" label="Debt weight" value={state.debtWeight} onChange={update('debtWeight')} />
                    <DecimalField id="equity-weight" label="Equity weight" value={state.equityWeight} onChange={update('equityWeight')} />
                </AssumptionGroup>
                <AssumptionGroup title="Capital bridge" description="Use base currency units and share counts.">
                    <DecimalField id="terminal-growth" label="Terminal growth" value={state.terminalGrowth} onChange={update('terminalGrowth')} />
                    <DecimalField id="cash" label="Cash" value={state.cash} onChange={update('cash')} />
                    <DecimalField id="debt" label="Debt" value={state.debt} onChange={update('debt')} />
                    <DecimalField id="preferred-stock" label="Preferred stock" value={state.preferredStock} onChange={update('preferredStock')} />
                    <DecimalField id="lease-liabilities" label="Lease liabilities" value={state.leaseLiabilities} onChange={update('leaseLiabilities')} />
                    <DecimalField id="non-controlling-interest" label="Non-controlling interest" value={state.nonControllingInterest} onChange={update('nonControllingInterest')} />
                    <DecimalField id="diluted-shares" label="Diluted shares" value={state.dilutedShares} onChange={update('dilutedShares')} />
                    <Field label="Assumption trace" htmlFor="trace-description"><Input id="trace-description" value={state.traceDescription} onChange={update('traceDescription')} placeholder="Why these inputs are appropriate" /></Field>
                </AssumptionGroup>
            </div>
            {touched && error && (
                <Alert variant="warning" className="mt-3" role="status">
                    <CircleAlert className="size-4" />
                    <AlertTitle>Valuation input incomplete</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}
        </fieldset>
    );
}

function AssumptionGroup({ title, description, children }: { title: string; description: string; children: ReactNode }) {
    return (
        <section className="space-y-2 rounded-md border border-border/70 p-3" aria-label={title}>
            <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide">{title}</h3>
                <p className="text-xs text-muted-foreground">{description}</p>
            </div>
            {children}
        </section>
    );
}

function DecimalField({ id, label, value, onChange, placeholder }: { id: string; label: string; value: string; onChange: (event: ChangeEvent<HTMLInputElement>) => void; placeholder?: string }) {
    return <Field label={label} htmlFor={id}><Input id={id} inputMode="decimal" value={value} onChange={onChange} placeholder={placeholder} /></Field>;
}
