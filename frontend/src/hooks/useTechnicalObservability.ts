import { useCallback } from 'react';

import useSWR from 'swr';

import { clientLogger } from '@/lib/logger';
import {
    buildTechnicalObservabilitySearchParams,
    parseTechnicalCalibrationObservationBuildResultResponse,
    parseTechnicalMonitoringAggregatesResponse,
    parseTechnicalMonitoringEventDetailResponse,
    parseTechnicalMonitoringRowsResponse,
    TechnicalCalibrationObservationBuildResultModel,
    TechnicalMonitoringAggregateModel,
    TechnicalMonitoringEventDetailModel,
    TechnicalMonitoringRowModel,
    TechnicalObservabilityFilters,
} from '@/types/technical-observability';
import { parseApiErrorMessage } from '@/types/protocol';

const API_URL = process.env.NEXT_PUBLIC_LANGGRAPH_URL || 'http://localhost:8000';

const readErrorMessage = async (response: Response): Promise<string> => {
    try {
        const raw: unknown = await response.json();
        return (
            parseApiErrorMessage(raw) ||
            `Failed to fetch observability data (HTTP ${response.status}).`
        );
    } catch {
        return `Failed to fetch observability data (HTTP ${response.status}).`;
    }
};

async function fetchTypedJson<T>(url: string, context: string): Promise<T> {
    clientLogger.debug('technical_observability.fetch.start', { url, context });
    try {
        const response = await fetch(url);
        if (!response.ok) {
            clientLogger.error('technical_observability.fetch.http_error', {
                url,
                context,
                status: response.status,
                statusText: response.statusText,
            });
            throw new Error(await readErrorMessage(response));
        }
        const data = await response.json();
        clientLogger.debug('technical_observability.fetch.success', {
            url,
            context,
        });
        return data;
    } catch (error) {
        clientLogger.error('technical_observability.fetch.error', {
            url,
            context,
            error: error instanceof Error ? error.message : String(error),
        });
        throw error;
    }
}

export function useTechnicalObservability(
    filters: TechnicalObservabilityFilters
) {
    const baseParams = buildTechnicalObservabilitySearchParams(filters).toString();
    const aggregatesUrl = `${API_URL}/api/observability/monitoring/aggregates?${baseParams}`;
    const rowsUrl = `${API_URL}/api/observability/monitoring/rows?${baseParams}`;
    const calibrationUrl = `${API_URL}/api/observability/calibration/direction-readiness?${baseParams}`;

    const fetchAggregates = useCallback(
        (url: string) =>
            fetchTypedJson<unknown>(
                url,
                'technical_observability.aggregates'
            ).then(parseTechnicalMonitoringAggregatesResponse),
        []
    );
    const fetchRows = useCallback(
        (url: string) =>
            fetchTypedJson<unknown>(
                url,
                'technical_observability.rows'
            ).then(parseTechnicalMonitoringRowsResponse),
        []
    );
    const fetchCalibration = useCallback(
        (url: string) =>
            fetchTypedJson<unknown>(
                url,
                'technical_observability.calibration'
            ).then(parseTechnicalCalibrationObservationBuildResultResponse),
        []
    );

    const aggregatesState = useSWR<TechnicalMonitoringAggregateModel[]>(
        aggregatesUrl,
        fetchAggregates,
        {
            revalidateOnFocus: false,
            dedupingInterval: 30_000,
            shouldRetryOnError: false,
        }
    );
    const rowsState = useSWR<TechnicalMonitoringRowModel[]>(rowsUrl, fetchRows, {
        revalidateOnFocus: false,
        dedupingInterval: 30_000,
        shouldRetryOnError: false,
    });
    const calibrationState = useSWR<TechnicalCalibrationObservationBuildResultModel>(
        calibrationUrl,
        fetchCalibration,
        {
            revalidateOnFocus: false,
            dedupingInterval: 30_000,
            shouldRetryOnError: false,
        }
    );

    return {
        aggregates: aggregatesState.data ?? [],
        rows: rowsState.data ?? [],
        calibrationReadiness: calibrationState.data ?? null,
        isLoading:
            aggregatesState.isLoading ||
            rowsState.isLoading ||
            calibrationState.isLoading,
        error:
            aggregatesState.error ||
            rowsState.error ||
            calibrationState.error ||
            null,
    };
}

export function useTechnicalObservabilityEventDetail(
    eventId: string | null,
    labelingMethodVersion: string
) {
    const url =
        eventId === null
            ? null
            : `${API_URL}/api/observability/monitoring/events/${eventId}?${buildTechnicalObservabilitySearchParams(
                  {
                      tickers: [],
                      agentSources: [],
                      timeframes: [],
                      horizons: [],
                      logicVersions: [],
                      directions: [],
                      runTypes: [],
                      reliabilityLevels: [],
                      eventTimeStart: null,
                      eventTimeEnd: null,
                      resolvedTimeStart: null,
                      resolvedTimeEnd: null,
                      labelingMethodVersion,
                      limit: 200,
                      datePreset: 'all_time',
                  }
              ).toString()}`;

    const fetchEventDetail = useCallback(
        (requestUrl: string) =>
            fetchTypedJson<unknown>(
                requestUrl,
                'technical_observability.event_detail'
            ).then(parseTechnicalMonitoringEventDetailResponse),
        []
    );

    const state = useSWR<TechnicalMonitoringEventDetailModel>(
        url,
        fetchEventDetail,
        {
            revalidateOnFocus: false,
            dedupingInterval: 30_000,
            shouldRetryOnError: false,
        }
    );

    return {
        detail: state.data ?? null,
        isLoading: state.isLoading,
        error: state.error ?? null,
    };
}
