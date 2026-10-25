import type { Metadata } from 'next';

import { TechnicalObservabilityPage as TechnicalObservabilityView } from '@/features/technical-observability/technical-observability-page';

export const metadata: Metadata = {
    title: 'Technical Observability | FinanceAI Lab',
    description:
        'Internal monitoring workspace for technical prediction events, outcomes, and calibration readiness.',
};

export default function TechnicalObservabilityPage() {
    return <TechnicalObservabilityView />;
}
