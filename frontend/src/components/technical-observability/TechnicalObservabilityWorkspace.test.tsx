import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, it, vi } from 'vitest';

import { TechnicalObservabilityWorkspace } from './TechnicalObservabilityWorkspace';

const mockUseTechnicalObservability = vi.fn();
const mockUseTechnicalObservabilityEventDetail = vi.fn();

vi.mock('next/link', () => ({
    default: ({
        children,
        href,
        ...rest
    }: {
        children: React.ReactNode;
        href: string;
    }) => (
        <a href={href} {...rest}>
            {children}
        </a>
    ),
}));

vi.mock('@/hooks/useTechnicalObservability', () => ({
    useTechnicalObservability: (...args: unknown[]) =>
        mockUseTechnicalObservability(...args),
    useTechnicalObservabilityEventDetail: (...args: unknown[]) =>
        mockUseTechnicalObservabilityEventDetail(...args),
}));

describe('TechnicalObservabilityWorkspace', () => {
    afterEach(() => {
        cleanup();
    });

    beforeEach(() => {
        mockUseTechnicalObservability.mockReturnValue({
            aggregates: [
                {
                    timeframe: '1d',
                    horizon: '1d',
                    logic_version: 'v1',
                    event_count: 4,
                    labeled_event_count: 3,
                    unresolved_event_count: 1,
                    avg_forward_return: 0.024,
                    avg_mfe: 0.041,
                    avg_mae: -0.012,
                    avg_realized_volatility: 0.19,
                },
                {
                    timeframe: '1wk',
                    horizon: '5d',
                    logic_version: 'v2',
                    event_count: 6,
                    labeled_event_count: 4,
                    unresolved_event_count: 2,
                    avg_forward_return: 0.038,
                    avg_mfe: 0.067,
                    avg_mae: -0.019,
                    avg_realized_volatility: 0.24,
                },
            ],
            rows: [
                {
                    event_id: 'evt-1',
                    event_time: '2026-03-20T00:00:00Z',
                    ticker: 'AAPL',
                    agent_source: 'technical_analysis',
                    timeframe: '1d',
                    horizon: '1d',
                    direction: 'bullish',
                    logic_version: 'v1',
                    run_type: 'workflow',
                    confidence: 0.72,
                    raw_score: 1.1,
                    forward_return: 0.024,
                    mfe: 0.041,
                    mae: -0.012,
                    resolved_at: null,
                    data_quality_flags: ['delayed_market_data'],
                },
            ],
            calibrationReadiness: {
                row_count: 3,
                usable_row_count: 2,
                dropped_row_count: 1,
                dropped_reasons: { missing_outcome_path: 1 },
                observations: [
                    {
                        direction: 'bullish',
                        timeframe: '1d',
                        horizon: '1d',
                        raw_score: 1.1,
                        target_outcome: 1,
                    },
                    {
                        direction: 'bearish',
                        timeframe: '1wk',
                        horizon: '5d',
                        raw_score: -0.8,
                        target_outcome: 0,
                    },
                ],
            },
            isLoading: false,
            error: null,
        });
        mockUseTechnicalObservabilityEventDetail.mockReturnValue({
            detail: {
                event_id: 'evt-1',
                event_time: '2026-03-20T00:00:00Z',
                ticker: 'AAPL',
                agent_source: 'technical_analysis',
                timeframe: '1d',
                horizon: '1d',
                direction: 'bullish',
                logic_version: 'v1',
                feature_contract_version: 'technical_feature_contract_v1',
                run_type: 'workflow',
                full_report_artifact_id: 'art-1',
                source_artifact_refs: { feature_pack: 'art-2' },
                context_payload: { regime: 'trend', setup_quality: 'high' },
                data_quality_flags: ['delayed_market_data'],
                forward_return: 0.024,
                realized_volatility: 0.19,
                mfe: 0.041,
                mae: -0.012,
            },
            isLoading: false,
            error: null,
        });
    });

    it('renders overview KPI and backlog summary content', () => {
        render(<TechnicalObservabilityWorkspace />);

        screen.getByRole('heading', { name: 'Technical Observability' });
        screen.getByLabelText('Tickers');
        screen.getAllByText('Label Coverage');
        screen.getAllByText('70%');
        screen.getByText('Outcome collection pressure points');
        screen.getByText('AAPL · bullish');
    });

    it('switches to event explorer and opens the event detail drill-down', () => {
        render(<TechnicalObservabilityWorkspace />);

        fireEvent.click(screen.getByRole('button', { name: 'Event Explorer' }));
        fireEvent.click(screen.getByRole('button', { name: 'Inspect evt-1' }));

        screen.getByText('Artifact References');
        screen.getByText('art-1');
        screen.getByText('setup quality');
    });

    it('shows loading copy when the overview is still refreshing', () => {
        mockUseTechnicalObservability.mockReturnValue({
            aggregates: [],
            rows: [],
            calibrationReadiness: null,
            isLoading: true,
            error: null,
        });

        render(<TechnicalObservabilityWorkspace />);

        screen.getByText('Refreshing monitoring summary');
    });

    it('shows an empty state when no observability rows match the filters', () => {
        mockUseTechnicalObservability.mockReturnValue({
            aggregates: [],
            rows: [],
            calibrationReadiness: null,
            isLoading: false,
            error: null,
        });

        render(<TechnicalObservabilityWorkspace />);

        screen.getByText('No observability data matches the current scope');
    });

    it('shows a degraded banner when the read model responds with an error', () => {
        mockUseTechnicalObservability.mockReturnValue({
            aggregates: [],
            rows: [],
            calibrationReadiness: null,
            isLoading: false,
            error: new Error('backend unavailable'),
        });

        render(<TechnicalObservabilityWorkspace />);

        screen.getByText('Read model returned a degraded response');
        screen.getByText('backend unavailable');
    });

    it('renders cohort analysis slices under the raw outcomes lens', () => {
        render(<TechnicalObservabilityWorkspace />);

        fireEvent.click(screen.getByRole('button', { name: 'Cohort Analysis' }));

        screen.getByText('Cohort Slices');
        screen.getByText('1D timeframe');
        screen.getByText('1WK timeframe');
        screen.getAllByText('Avg Forward Return');
    });

    it('keeps approved snapshots separate from raw cohort truth', () => {
        render(<TechnicalObservabilityWorkspace />);

        fireEvent.click(screen.getByRole('button', { name: 'Cohort Analysis' }));
        fireEvent.click(screen.getByRole('button', { name: 'Approved Snapshots' }));

        screen.getByText('Approved snapshots stay separate from raw cohort truth');
    });

    it('renders calibration readiness sample sufficiency and drop reasons', () => {
        render(<TechnicalObservabilityWorkspace />);

        fireEvent.click(screen.getByRole('button', { name: 'Calibration Readiness' }));

        screen.getByText('Candidate Rows');
        screen.getByText('Readiness Ratio');
        screen.getByText('Builder-ready calibration depth');
        screen.getByText('missing outcome path');
    });
});
