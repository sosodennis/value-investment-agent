import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import type { ExactAmount } from './fundamental-report-model';

export type EvidenceActionProps = { onSelectEvidence?: (item: EvidenceSelection) => void };

export function ExactValue({ amount, onSelectEvidence }: EvidenceActionProps & { amount: ExactAmount | null }) {
    return amount ? <InspectionValue evidence={amount.evidence} onSelectEvidence={onSelectEvidence} /> : (
        <span className="text-sm font-normal text-muted-foreground">Unavailable</span>
    );
}

export function InspectionValue({
    evidence,
    onSelectEvidence,
}: EvidenceActionProps & {
    evidence: EvidenceSelection;
}) {
    const value = evidence.displayValue ?? evidence.value;
    return onSelectEvidence ? (
        <button
            type="button"
            className="max-w-full rounded-sm text-left font-mono tabular-nums underline decoration-dashed decoration-muted-foreground underline-offset-4 [overflow-wrap:anywhere] hover:decoration-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onSelectEvidence(evidence)}
            aria-label={`Inspect ${evidence.title}`}
        >
            {value}
        </button>
    ) : (
        <span className="font-mono tabular-nums [overflow-wrap:anywhere]">{value}</span>
    );
}
