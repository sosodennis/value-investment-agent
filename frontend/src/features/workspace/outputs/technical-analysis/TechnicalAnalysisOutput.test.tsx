import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { TechnicalAnalysisOutput } from './TechnicalAnalysisOutput';

const mockUseArtifact = vi.fn();
const mockFeatureRetry = vi.fn();

vi.mock('../../../../hooks/useArtifact', () => ({
    useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

describe('TechnicalAnalysisOutput', () => {
    beforeEach(() => {
        mockFeatureRetry.mockReset();
        mockUseArtifact.mockImplementation((target: unknown) => {
            const artifactId = typeof target === 'string'
                ? target
                : target && typeof target === 'object' && 'download_url' in target && typeof target.download_url === 'string'
                    ? decodeURIComponent(new URL(target.download_url, 'http://test').pathname.split('/').pop() ?? '')
                    : null;
            if (artifactId === 'feature-1') {
                return {
                    data: null,
                    isLoading: false,
                    error: new Error('Feature pack temporarily unavailable.'),
                    retry: mockFeatureRetry,
                    isRetrying: false,
                    retryable: true,
                };
            }
            if (artifactId === 'report-1') {
                return {
                    data: {
                        schema_version: '2.0',
                        ticker: 'AAPL',
                        as_of: '2026-03-18T08:00:00Z',
                        direction: 'BULLISH_EXTENSION',
                        risk_level: 'medium',
                        artifact_refs: { feature_pack_id: 'feature-1' },
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
                            quant_context_summary: {
                                timeframe: '1d',
                                volatility_regime: 'ELEVATED',
                                liquidity_regime: 'LIQUID',
                                stretch_state: 'HIGH',
                                alignment_state: 'FULL_BULLISH_ALIGNMENT',
                                alignment_ratio: 1.0,
                                price_vs_sma20_z: 1.34,
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
                        signal_strength_summary: {
                            raw_value: 0.74,
                            effective_value: 0.58,
                            display_percent: 58.0,
                            strength_level: 'moderate',
                            calibration_status: 'ineligible',
                            source: 'fusion_runtime',
                            probability_eligible: false,
                        },
                        setup_reliability_summary: {
                            level: 'low',
                            calibration_status: 'ineligible',
                            coverage_status: 'partial',
                            conflict_level: 'present',
                            reasons: ['UNCALIBRATED', 'DEGRADED_INPUTS', 'CONFLICT_PRESENT', 'PARTIAL_COVERAGE'],
                            recommended_reliance: 'cautious',
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
                    retry: vi.fn(),
                    isRetrying: false,
                    retryable: false,
                };
            }
            return {
                data: null,
                isLoading: false,
                error: null,
                retry: vi.fn(),
                isRetrying: false,
                retryable: false,
            };
        });
    });

    it('renders report-level key evidence quality coverage and policy alerts', () => {
        render(
            <TechnicalAnalysisOutput
                reference={{
                    artifact_id: 'report-1',
                    download_url: '/api/v1/artifacts/report-1?run_id=run-technical-1',
                    type: 'technical_analysis.output',
                }}
                previewData={null}
                status="done"
            />
        );

        expect(screen.getAllByText('Signal Strength').length).toBeGreaterThan(0);
        screen.getByText('Setup Reliability');
        screen.getByText('Moderate');
        screen.getByText('Low Reliability');
        expect(screen.queryByText(/^Confidence$/i)).toBeNull();
        screen.getByText(/Not a probability forecast/i);
        screen.getByText('Key Evidence');
        screen.getByText('Bull Trend');
        screen.getByText('Structure Map');
        screen.getByText('Breakout Up');
        screen.getByText('Quant Context');
        screen.getByText('Full Bullish Alignment');
        screen.getByText('Quality & Coverage');
        screen.getByText('Partial Coverage');
        screen.getByText('Policy Alerts');
        screen.getByText('RSI oversold near support');
        screen.getByText(/Active \/ Monitoring/i);
        screen.getByText('Observability Summary');
        screen.getByText(/Loaded Artifacts: 5/i);
        screen.getByText('Missing · Direction Scorecard');
    });

    it('shows an error state when the completed run cannot load its report artifact', () => {
        mockUseArtifact.mockReturnValue({
            data: null,
            isLoading: false,
            error: new Error('Artifact request failed.'),
        });

        render(
            <TechnicalAnalysisOutput
                reference={{
                    artifact_id: 'report-failed',
                    download_url: '/api/v1/artifacts/report-failed',
                    type: 'technical_analysis.output',
                }}
                previewData={null}
                status="done"
            />
        );

        screen.getByRole('alert');
        screen.getByText('Technical report unavailable');
        screen.getByText('Artifact request failed.');
        expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
        expect(screen.queryByText('Processing Statistical Framework…')).toBeNull();
    });

    it('retries an unavailable supplementary artifact without replacing the technical report', () => {
        render(
            <TechnicalAnalysisOutput
                reference={{
                    artifact_id: 'report-1',
                    download_url: '/api/v1/artifacts/report-1?run_id=run-technical-1',
                    type: 'technical_analysis.output',
                }}
                previewData={null}
                status="done"
            />
        );

        expect(screen.getAllByText('Signal Strength').length).toBeGreaterThan(0);
        const featurePackButton = screen
            .getAllByRole('button', { name: /feature pack/i })
            .find((button) => button.textContent?.trim() === 'Feature Pack');
        if (!featurePackButton) throw new Error('Feature Pack control is unavailable.');
        fireEvent.click(featurePackButton);
        const featurePackTarget = mockUseArtifact.mock.calls
            .map(([target]) => target)
            .find((target) => target && typeof target === 'object' && 'artifact_id' in target && target.artifact_id === 'feature-1');
        expect(featurePackTarget).toMatchObject({
            artifact_id: 'feature-1',
            download_url: '/api/v1/artifacts/feature-1?run_id=run-technical-1',
        });
        screen.getByText('Feature pack temporarily unavailable.');
        fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

        expect(mockFeatureRetry).toHaveBeenCalledOnce();
        expect(screen.getAllByText('Signal Strength').length).toBeGreaterThan(0);
    });
});
