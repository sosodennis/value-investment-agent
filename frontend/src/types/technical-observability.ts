import type { components } from '@/types/generated/api-contract';
import { isRecord } from '@/types/preview';

export type TechnicalMonitoringAggregateModel =
    components['schemas']['TechnicalMonitoringAggregateModel'];
export type TechnicalMonitoringEventDetailModel =
    components['schemas']['TechnicalMonitoringEventDetailModel'];
export type TechnicalMonitoringRowModel =
    components['schemas']['TechnicalMonitoringRowModel'];
export type TechnicalCalibrationObservationBuildResultModel =
    components['schemas']['TechnicalCalibrationObservationBuildResultModel'];

export type TechnicalObservabilityView =
    | 'overview'
    | 'events'
    | 'cohorts'
    | 'calibration';

export type TechnicalObservabilityDatePreset =
    | 'last_7d'
    | 'last_30d'
    | 'last_90d'
    | 'all_time';

export type TechnicalObservabilityFilters = {
    tickers: string[];
    agentSources: string[];
    timeframes: string[];
    horizons: string[];
    logicVersions: string[];
    directions: string[];
    runTypes: string[];
    reliabilityLevels: string[];
    eventTimeStart: string | null;
    eventTimeEnd: string | null;
    resolvedTimeStart: string | null;
    resolvedTimeEnd: string | null;
    labelingMethodVersion: string;
    limit: number;
    datePreset: TechnicalObservabilityDatePreset;
};

export const TECHNICAL_OBSERVABILITY_VIEWS: TechnicalObservabilityView[] = [
    'overview',
    'events',
    'cohorts',
    'calibration',
];

const DEFAULT_LABELING_METHOD_VERSION = 'technical_outcome_labeling.v1';
const DATE_PRESET_VALUES: TechnicalObservabilityDatePreset[] = [
    'last_7d',
    'last_30d',
    'last_90d',
    'all_time',
];

export function createDefaultTechnicalObservabilityFilters(
    now: Date = new Date()
): TechnicalObservabilityFilters {
    const eventTimeStart = subtractDays(now, 30).toISOString();
    return {
        tickers: [],
        agentSources: [],
        timeframes: [],
        horizons: [],
        logicVersions: [],
        directions: [],
        runTypes: [],
        reliabilityLevels: [],
        eventTimeStart,
        eventTimeEnd: null,
        resolvedTimeStart: null,
        resolvedTimeEnd: null,
        labelingMethodVersion: DEFAULT_LABELING_METHOD_VERSION,
        limit: 200,
        datePreset: 'last_30d',
    };
}

export function applyTechnicalObservabilityDatePreset(
    preset: TechnicalObservabilityDatePreset,
    now: Date = new Date()
): Pick<
    TechnicalObservabilityFilters,
    'datePreset' | 'eventTimeStart' | 'eventTimeEnd'
> {
    if (preset === 'all_time') {
        return {
            datePreset: preset,
            eventTimeStart: null,
            eventTimeEnd: null,
        };
    }

    const days = preset === 'last_7d' ? 7 : preset === 'last_90d' ? 90 : 30;
    return {
        datePreset: preset,
        eventTimeStart: subtractDays(now, days).toISOString(),
        eventTimeEnd: null,
    };
}

export function parseTechnicalObservabilityDatePreset(
    value: string
): TechnicalObservabilityDatePreset {
    if (isTechnicalObservabilityDatePreset(value)) {
        return value;
    }
    return 'last_30d';
}

export function buildTechnicalObservabilitySearchParams(
    filters: TechnicalObservabilityFilters,
    extra?: Record<string, string | number | boolean | null | undefined>
): URLSearchParams {
    const params = new URLSearchParams();

    appendList(params, 'tickers', filters.tickers);
    appendList(params, 'agent_sources', filters.agentSources);
    appendList(params, 'timeframes', filters.timeframes);
    appendList(params, 'horizons', filters.horizons);
    appendList(params, 'logic_versions', filters.logicVersions);
    appendList(params, 'directions', filters.directions);
    appendList(params, 'run_types', filters.runTypes);
    appendList(params, 'reliability_levels', filters.reliabilityLevels);
    appendOptional(params, 'event_time_start', filters.eventTimeStart);
    appendOptional(params, 'event_time_end', filters.eventTimeEnd);
    appendOptional(params, 'resolved_time_start', filters.resolvedTimeStart);
    appendOptional(params, 'resolved_time_end', filters.resolvedTimeEnd);
    appendOptional(
        params,
        'labeling_method_version',
        filters.labelingMethodVersion.trim()
    );
    params.set('limit', String(filters.limit));

    if (extra) {
        for (const [key, value] of Object.entries(extra)) {
            if (value === null || value === undefined || value === '') {
                continue;
            }
            params.set(key, String(value));
        }
    }

    return params;
}

export function parseFilterListInput(value: string): string[] {
    return value
        .split(',')
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean);
}

export function parseTechnicalMonitoringAggregatesResponse(
    value: unknown
): TechnicalMonitoringAggregateModel[] {
    if (!Array.isArray(value)) {
        throw new TypeError('Technical monitoring aggregates response must be an array.');
    }
    return value.map((entry, index) =>
        parseTechnicalMonitoringAggregateModel(
            entry,
            `technical_observability.aggregates[${index}]`
        )
    );
}

export function parseTechnicalMonitoringRowsResponse(
    value: unknown
): TechnicalMonitoringRowModel[] {
    if (!Array.isArray(value)) {
        throw new TypeError('Technical monitoring rows response must be an array.');
    }
    return value.map((entry, index) =>
        parseTechnicalMonitoringRowModel(
            entry,
            `technical_observability.rows[${index}]`
        )
    );
}

export function parseTechnicalMonitoringEventDetailResponse(
    value: unknown
): TechnicalMonitoringEventDetailModel {
    return parseTechnicalMonitoringEventDetailModel(
        value,
        'technical_observability.event_detail'
    );
}

export function parseTechnicalCalibrationObservationBuildResultResponse(
    value: unknown
): TechnicalCalibrationObservationBuildResultModel {
    const record = toRecord(
        value,
        'technical_observability.calibration_build_result'
    );
    const result: TechnicalCalibrationObservationBuildResultModel = {
        dropped_reasons: parseNumberMap(
            record.dropped_reasons,
            'technical_observability.calibration_build_result.dropped_reasons'
        ),
        dropped_row_count: parseNumber(
            record.dropped_row_count,
            'technical_observability.calibration_build_result.dropped_row_count'
        ),
        row_count: parseNumber(
            record.row_count,
            'technical_observability.calibration_build_result.row_count'
        ),
        usable_row_count: parseNumber(
            record.usable_row_count,
            'technical_observability.calibration_build_result.usable_row_count'
        ),
    };

    if (record.observations === undefined || record.observations === null) {
        result.observations = record.observations ?? null;
        return result;
    }

    if (!Array.isArray(record.observations)) {
        throw new TypeError(
            'technical_observability.calibration_build_result.observations must be an array.'
        );
    }

    result.observations = record.observations.map((entry, index) =>
        parseTechnicalDirectionCalibrationObservationModel(
            entry,
            `technical_observability.calibration_build_result.observations[${index}]`
        )
    );
    return result;
}

function subtractDays(value: Date, days: number): Date {
    const next = new Date(value);
    next.setUTCDate(next.getUTCDate() - days);
    return next;
}

function appendList(
    params: URLSearchParams,
    key: string,
    values: readonly string[]
): void {
    for (const value of values) {
        if (!value) {
            continue;
        }
        params.append(key, value);
    }
}

function appendOptional(
    params: URLSearchParams,
    key: string,
    value: string | null
): void {
    if (!value) {
        return;
    }
    params.set(key, value);
}

function isTechnicalObservabilityDatePreset(
    value: string
): value is TechnicalObservabilityDatePreset {
    return DATE_PRESET_VALUES.some((preset) => preset === value);
}

function toRecord(value: unknown, context: string): Record<string, unknown> {
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
}

function parseString(value: unknown, context: string): string {
    if (typeof value !== 'string') {
        throw new TypeError(`${context} must be a string.`);
    }
    return value;
}

function parseNumber(value: unknown, context: string): number {
    if (typeof value !== 'number' || Number.isNaN(value)) {
        throw new TypeError(`${context} must be a number.`);
    }
    return value;
}

function parseNullableNumber(
    value: unknown,
    context: string
): number | null | undefined {
    if (value === undefined || value === null) {
        return value;
    }
    return parseNumber(value, context);
}

function parseNullableString(
    value: unknown,
    context: string
): string | null | undefined {
    if (value === undefined || value === null) {
        return value;
    }
    return parseString(value, context);
}

function parseStringArray(value: unknown, context: string): string[] {
    if (!Array.isArray(value)) {
        throw new TypeError(`${context} must be an array.`);
    }
    return value.map((entry, index) => parseString(entry, `${context}[${index}]`));
}

function parseNumberMap(
    value: unknown,
    context: string
): Record<string, number> {
    const record = toRecord(value, context);
    const next: Record<string, number> = {};
    for (const [key, entry] of Object.entries(record)) {
        next[key] = parseNumber(entry, `${context}.${key}`);
    }
    return next;
}

function parseUnknownRecord(
    value: unknown,
    context: string
): Record<string, unknown> {
    return toRecord(value, context);
}

function parseTechnicalMonitoringAggregateModel(
    value: unknown,
    context: string
): TechnicalMonitoringAggregateModel {
    const record = toRecord(value, context);
    const model: TechnicalMonitoringAggregateModel = {
        event_count: parseNumber(record.event_count, `${context}.event_count`),
        horizon: parseString(record.horizon, `${context}.horizon`),
        labeled_event_count: parseNumber(
            record.labeled_event_count,
            `${context}.labeled_event_count`
        ),
        logic_version: parseString(record.logic_version, `${context}.logic_version`),
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
        unresolved_event_count: parseNumber(
            record.unresolved_event_count,
            `${context}.unresolved_event_count`
        ),
    };

    assignIfDefined(
        model,
        'avg_confidence',
        parseNullableNumber(record.avg_confidence, `${context}.avg_confidence`)
    );
    assignIfDefined(
        model,
        'avg_forward_return',
        parseNullableNumber(
            record.avg_forward_return,
            `${context}.avg_forward_return`
        )
    );
    assignIfDefined(
        model,
        'avg_mae',
        parseNullableNumber(record.avg_mae, `${context}.avg_mae`)
    );
    assignIfDefined(
        model,
        'avg_mfe',
        parseNullableNumber(record.avg_mfe, `${context}.avg_mfe`)
    );
    assignIfDefined(
        model,
        'avg_raw_score',
        parseNullableNumber(record.avg_raw_score, `${context}.avg_raw_score`)
    );
    assignIfDefined(
        model,
        'avg_realized_volatility',
        parseNullableNumber(
            record.avg_realized_volatility,
            `${context}.avg_realized_volatility`
        )
    );
    assignIfDefined(
        model,
        'first_event_time',
        parseNullableString(record.first_event_time, `${context}.first_event_time`)
    );
    assignIfDefined(
        model,
        'last_event_time',
        parseNullableString(record.last_event_time, `${context}.last_event_time`)
    );
    return model;
}

function parseTechnicalMonitoringRowModel(
    value: unknown,
    context: string
): TechnicalMonitoringRowModel {
    const record = toRecord(value, context);
    const model: TechnicalMonitoringRowModel = {
        agent_source: parseString(record.agent_source, `${context}.agent_source`),
        data_quality_flags: parseStringArray(
            record.data_quality_flags,
            `${context}.data_quality_flags`
        ),
        direction: parseString(record.direction, `${context}.direction`),
        event_id: parseString(record.event_id, `${context}.event_id`),
        event_time: parseString(record.event_time, `${context}.event_time`),
        horizon: parseString(record.horizon, `${context}.horizon`),
        logic_version: parseString(record.logic_version, `${context}.logic_version`),
        run_type: parseString(record.run_type, `${context}.run_type`),
        ticker: parseString(record.ticker, `${context}.ticker`),
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
    };

    assignIfDefined(
        model,
        'confidence',
        parseNullableNumber(record.confidence, `${context}.confidence`)
    );
    assignIfDefined(
        model,
        'forward_return',
        parseNullableNumber(record.forward_return, `${context}.forward_return`)
    );
    assignIfDefined(
        model,
        'labeling_method_version',
        parseNullableString(
            record.labeling_method_version,
            `${context}.labeling_method_version`
        )
    );
    assignIfDefined(model, 'mae', parseNullableNumber(record.mae, `${context}.mae`));
    assignIfDefined(model, 'mfe', parseNullableNumber(record.mfe, `${context}.mfe`));
    assignIfDefined(
        model,
        'outcome_path_id',
        parseNullableString(record.outcome_path_id, `${context}.outcome_path_id`)
    );
    assignIfDefined(
        model,
        'raw_score',
        parseNullableNumber(record.raw_score, `${context}.raw_score`)
    );
    assignIfDefined(
        model,
        'realized_volatility',
        parseNullableNumber(
            record.realized_volatility,
            `${context}.realized_volatility`
        )
    );
    assignIfDefined(
        model,
        'reliability_level',
        parseNullableString(
            record.reliability_level,
            `${context}.reliability_level`
        )
    );
    assignIfDefined(
        model,
        'resolved_at',
        parseNullableString(record.resolved_at, `${context}.resolved_at`)
    );
    return model;
}

function parseTechnicalMonitoringEventDetailModel(
    value: unknown,
    context: string
): TechnicalMonitoringEventDetailModel {
    const record = toRecord(value, context);
    const model: TechnicalMonitoringEventDetailModel = {
        agent_source: parseString(record.agent_source, `${context}.agent_source`),
        context_payload: parseUnknownRecord(
            record.context_payload,
            `${context}.context_payload`
        ),
        data_quality_flags: parseStringArray(
            record.data_quality_flags,
            `${context}.data_quality_flags`
        ),
        direction: parseString(record.direction, `${context}.direction`),
        event_id: parseString(record.event_id, `${context}.event_id`),
        event_time: parseString(record.event_time, `${context}.event_time`),
        feature_contract_version: parseString(
            record.feature_contract_version,
            `${context}.feature_contract_version`
        ),
        full_report_artifact_id: parseString(
            record.full_report_artifact_id,
            `${context}.full_report_artifact_id`
        ),
        horizon: parseString(record.horizon, `${context}.horizon`),
        logic_version: parseString(record.logic_version, `${context}.logic_version`),
        run_type: parseString(record.run_type, `${context}.run_type`),
        source_artifact_refs: parseUnknownRecord(
            record.source_artifact_refs,
            `${context}.source_artifact_refs`
        ),
        ticker: parseString(record.ticker, `${context}.ticker`),
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
    };

    assignIfDefined(
        model,
        'confidence',
        parseNullableNumber(record.confidence, `${context}.confidence`)
    );
    assignIfDefined(
        model,
        'forward_return',
        parseNullableNumber(record.forward_return, `${context}.forward_return`)
    );
    assignIfDefined(
        model,
        'labeling_method_version',
        parseNullableString(
            record.labeling_method_version,
            `${context}.labeling_method_version`
        )
    );
    assignIfDefined(model, 'mae', parseNullableNumber(record.mae, `${context}.mae`));
    assignIfDefined(model, 'mfe', parseNullableNumber(record.mfe, `${context}.mfe`));
    assignIfDefined(
        model,
        'outcome_path_id',
        parseNullableString(record.outcome_path_id, `${context}.outcome_path_id`)
    );
    assignIfDefined(
        model,
        'raw_score',
        parseNullableNumber(record.raw_score, `${context}.raw_score`)
    );
    assignIfDefined(
        model,
        'realized_volatility',
        parseNullableNumber(
            record.realized_volatility,
            `${context}.realized_volatility`
        )
    );
    assignIfDefined(
        model,
        'reliability_level',
        parseNullableString(
            record.reliability_level,
            `${context}.reliability_level`
        )
    );
    assignIfDefined(
        model,
        'resolved_at',
        parseNullableString(record.resolved_at, `${context}.resolved_at`)
    );
    return model;
}

function parseTechnicalDirectionCalibrationObservationModel(
    value: unknown,
    context: string
): components['schemas']['TechnicalDirectionCalibrationObservationModel'] {
    const record = toRecord(value, context);
    return {
        direction: parseString(record.direction, `${context}.direction`),
        horizon: parseString(record.horizon, `${context}.horizon`),
        raw_score: parseNumber(record.raw_score, `${context}.raw_score`),
        target_outcome: parseNumber(
            record.target_outcome,
            `${context}.target_outcome`
        ),
        timeframe: parseString(record.timeframe, `${context}.timeframe`),
    };
}

function assignIfDefined<T extends object, K extends keyof T>(
    target: T,
    key: K,
    value: T[K] | undefined
): void {
    if (value !== undefined) {
        target[key] = value;
    }
}
