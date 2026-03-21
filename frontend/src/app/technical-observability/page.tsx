import type { Metadata } from 'next';

import { TechnicalObservabilityWorkspace } from '@/components/technical-observability/TechnicalObservabilityWorkspace';

export const metadata: Metadata = {
    title: 'Technical Observability | FinanceAI Lab',
    description:
        'Internal monitoring workspace for technical prediction events, outcomes, and calibration readiness.',
};

export default function TechnicalObservabilityPage() {
    return <TechnicalObservabilityWorkspace />;
}
