import type { EvidenceSelection } from '../../workspace-evidence-inspector';
import type { ExactAmount } from './fundamental-report-model';

export type EvidenceActionProps = { onSelectEvidence?: (item: EvidenceSelection) => void };

export function ExactValue({ amount }: { amount: ExactAmount | null }) {
    return amount ? (
        <span className="break-all font-mono tabular-nums">
            {amount.raw}{' '}
            <span className="text-xs font-normal text-muted-foreground">
                {amount.currency}
                {amount.basis === 'per-share' ? ' / share' : ' total equity'}
            </span>
        </span>
    ) : (
        <span className="text-sm font-normal text-muted-foreground">Unavailable</span>
    );
}

export function InspectionValue({
    value,
    evidence,
    onSelectEvidence,
}: EvidenceActionProps & {
    value: string;
    evidence: EvidenceSelection;
}) {
    return onSelectEvidence ? (
        <button
            type="button"
            className="break-all rounded-sm text-left font-mono tabular-nums underline decoration-dashed decoration-muted-foreground underline-offset-4 hover:decoration-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onSelectEvidence(evidence)}
            aria-label={`Inspect ${evidence.title}`}
        >
            {value}
        </button>
    ) : (
        <span className="break-all font-mono tabular-nums">{value}</span>
    );
}
