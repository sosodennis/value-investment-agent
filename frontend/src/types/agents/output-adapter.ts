import {
    DebatePreview,
    NewsPreview,
    TechnicalPreview,
    UnknownRecord,
    isRecord,
} from '../preview';
import { parseDebatePreview } from './debate-preview-parser';
import {
    parseFinancialPreview,
    ParsedFinancialPreview,
} from './fundamental-preview-parser';
import { parseNewsPreview } from './news-preview-parser';
import { parseTechnicalPreview } from './technical-preview-parser';
import {
    AgentErrorLog,
    AgentOutputKind,
    ArtifactReference,
    StandardAgentOutput,
} from './index';

interface OutputViewModelBase {
    agentId: string;
    summary: string | null;
    reference: ArtifactReference | null;
    errorLogs: AgentErrorLog[];
    outputKind: AgentOutputKind | null;
}

export interface FundamentalOutputViewModel extends OutputViewModelBase {
    kind: 'fundamental_analysis';
    preview: ParsedFinancialPreview | null;
}

export interface NewsOutputViewModel extends OutputViewModelBase {
    kind: 'financial_news_research';
    preview: NewsPreview | null;
}

export interface DebateOutputViewModel extends OutputViewModelBase {
    kind: 'debate';
    preview: DebatePreview | null;
}

export interface TechnicalOutputViewModel extends OutputViewModelBase {
    kind: 'technical_analysis';
    preview: TechnicalPreview | null;
}

export interface GenericOutputViewModel extends OutputViewModelBase {
    kind: 'generic';
    preview: UnknownRecord | null;
}

export type AgentOutputViewModel =
    | FundamentalOutputViewModel
    | NewsOutputViewModel
    | DebateOutputViewModel
    | TechnicalOutputViewModel
    | GenericOutputViewModel;

const parseGenericPreview = (
    value: unknown,
    context: string
): UnknownRecord | null => {
    if (value === undefined || value === null) return null;
    if (!isRecord(value) || Array.isArray(value)) {
        throw new TypeError(`${context} must be an object.`);
    }
    return value;
};

const buildBaseViewModel = (
    agentId: string,
    output: StandardAgentOutput | null
): OutputViewModelBase => ({
    agentId,
    summary: output?.summary ?? null,
    reference: output?.reference ?? null,
    errorLogs: output?.error_logs ?? [],
    outputKind: output?.kind ?? null,
});

export const parseFundamentalPreviewFromOutput = (
    output: StandardAgentOutput | null,
    context: string
): ParsedFinancialPreview | null =>
    parseFinancialPreview(output?.preview, `${context}.preview`);

export const parseNewsPreviewFromOutput = (
    output: StandardAgentOutput | null,
    context: string
): NewsPreview | null => parseNewsPreview(output?.preview, `${context}.preview`);

export const parseDebatePreviewFromOutput = (
    output: StandardAgentOutput | null,
    context: string
): DebatePreview | null =>
    parseDebatePreview(output?.preview, `${context}.preview`);

export const parseTechnicalPreviewFromOutput = (
    output: StandardAgentOutput | null,
    context: string
): TechnicalPreview | null =>
    parseTechnicalPreview(output?.preview, `${context}.preview`);

export const adaptAgentOutput = (
    agentId: string,
    output: StandardAgentOutput | null,
    context = 'agent_output'
): AgentOutputViewModel => {
    const base = buildBaseViewModel(agentId, output);
    if (output === null) {
        return {
            ...base,
            kind: 'generic',
            preview: null,
        };
    }

    if (output.kind === 'fundamental_analysis.output') {
        return {
            ...base,
            kind: 'fundamental_analysis',
            preview: parseFundamentalPreviewFromOutput(output, context),
        };
    }
    if (output.kind === 'financial_news_research.output') {
        return {
            ...base,
            kind: 'financial_news_research',
            preview: parseNewsPreviewFromOutput(output, context),
        };
    }
    if (output.kind === 'debate.output') {
        return {
            ...base,
            kind: 'debate',
            preview: parseDebatePreviewFromOutput(output, context),
        };
    }
    if (output.kind === 'technical_analysis.output') {
        return {
            ...base,
            kind: 'technical_analysis',
            preview: parseTechnicalPreviewFromOutput(output, context),
        };
    }

    return {
        ...base,
        kind: 'generic',
        preview: parseGenericPreview(output.preview, `${context}.preview`),
    };
};
