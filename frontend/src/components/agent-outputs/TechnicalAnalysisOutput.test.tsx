import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { TechnicalAnalysisOutput } from './TechnicalAnalysisOutput';

const mockUseArtifact = vi.fn();

vi.mock('../../hooks/useArtifact', () => ({
    useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

describe('TechnicalAnalysisOutput', () => {
    beforeEach(() => {
        mockUseArtifact.mockImplementation((artifactId: string | null | undefined) => {
            if (artifactId === 'report-1') {
                return {
                    data: {
                        schema_version: '2.0',
                        ticker: 'AAPL',
                        as_of: '2026-03-18T08:00:00Z',
                        direction: 'BULLISH_EXTENSION',
                        risk_level: 'medium',
                        artifact_refs: {},
                        summary_tags: ['trend_active'],
                        regime_summary: {
                            dominant_regime: 'BULL_TREND',
                            timeframe_count: 1,
                            average_confidence: 0.74,
                        },
                        structure_confluence_summary: {
                            timeframe: '1d',
                            confluence_state: 'strong',
                            confluence_score: 0.78,
                            poc: 182.5,
                            vah: 186.0,
                            val: 179.4,
                        },
                        evidence_bundle: {
                            primary_timeframe: '1d',
                            support_levels: [180.5, 176.2],
                            resistance_levels: [189.0],
                            breakout_signals: [
                                {
                                    name: 'BREAKOUT_UP',
                                    confidence: 0.72,
                                },
                            ],
                            scorecard_summary: {
                                timeframe: '1d',
                                overall_score: 0.68,
                                classic_label: 'constructive',
                                quant_label: 'balanced',
                            },
                            regime_summary: {
                                dominant_regime: 'BULL_TREND',
                                timeframe_count: 1,
                                average_confidence: 0.74,
                            },
                            structure_confluence_summary: {
                                timeframe: '1d',
                                confluence_state: 'strong',
                                confluence_score: 0.78,
                                poc: 182.5,
                                vah: 186.0,
                                val: 179.4,
                            },
                            conflict_reasons: ['1d:quant_neutral'],
                        },
                        quality_summary: {
                            is_degraded: true,
                            degraded_reasons: ['1wk_QUANT_SKIPPED'],
                            overall_quality: 'medium',
                            ready_timeframes: ['1d'],
                            degraded_timeframes: ['1wk'],
                            regime_inputs_ready_timeframes: ['1d'],
                            unavailable_indicator_count: 1,
                            alert_quality_gate_counts: {
                                passed: 1,
                                degraded: 1,
                            },
                            primary_timeframe: '1d',
                        },
                        alert_readout: {
                            total_alerts: 2,
                            policy_count: 2,
                            highest_severity: 'warning',
                            active_alert_count: 1,
                            monitoring_alert_count: 1,
                            suppressed_alert_count: 0,
                            quality_gate_counts: {
                                passed: 1,
                                degraded: 1,
                            },
                            top_alerts: [
                                {
                                    code: 'RSI_OVERSOLD',
                                    title: 'RSI oversold near support',
                                    severity: 'warning',
                                    timeframe: '1d',
                                    policy_code: 'TA_RSI_SUPPORT_REBOUND',
                                    lifecycle_state: 'active',
                                },
                            ],
                        },
                        observability_summary: {
                            primary_timeframe: '1d',
                            observed_timeframes: ['1d'],
                            loaded_artifacts: [
                                'feature_pack',
                                'pattern_pack',
                                'regime_pack',
                                'fusion_report',
                                'alerts',
                            ],
                            missing_artifacts: ['direction_scorecard'],
                            degraded_artifacts: ['feature_pack', 'fusion_report', 'alerts'],
                            loaded_artifact_count: 5,
                            missing_artifact_count: 1,
                            degraded_reason_count: 2,
                        },
                        diagnostics: {
                            is_degraded: true,
                            degraded_reasons: ['1wk_QUANT_SKIPPED'],
                        },
                    },
                    isLoading: false,
                    error: null,
                };
            }
            return {
                data: null,
                isLoading: false,
                error: null,
            };
        });
    });

    it('renders report-level key evidence quality coverage and policy alerts', () => {
        render(
            <TechnicalAnalysisOutput
                reference={{
                    artifact_id: 'report-1',
                    download_url: '/api/artifacts/report-1',
                    type: 'technical_analysis.output',
                }}
                previewData={null}
                status="done"
            />
        );

        expect(screen.getByText('Key Evidence')).not.toBeNull();
        expect(screen.getByText('Bull Trend')).not.toBeNull();
        expect(screen.getByText('Structure Map')).not.toBeNull();
        expect(screen.getByText('Breakout Up')).not.toBeNull();
        expect(screen.getByText('Quality & Coverage')).not.toBeNull();
        expect(screen.getByText('Partial Coverage')).not.toBeNull();
        expect(screen.getByText('Policy Alerts')).not.toBeNull();
        expect(screen.getByText('RSI oversold near support')).not.toBeNull();
        expect(screen.getByText(/Active \/ Monitoring/i)).not.toBeNull();
        expect(screen.getByText('Observability Summary')).not.toBeNull();
        expect(screen.getByText(/Loaded Artifacts: 5/i)).not.toBeNull();
        expect(screen.getByText('Missing · Direction Scorecard')).not.toBeNull();
    });
});
