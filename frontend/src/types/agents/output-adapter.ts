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
    ArtifactReference,
    StandardAgentOutput,
} from './index';

type CoreAgentId =
    | 'fundamental_analysis'
    | 'financial_news_research'
    | 'debate'
    | 'technical_analysis';

interface OutputViewModelBase {
    agentId: string;
    summary: string | null;
    reference: ArtifactReference | null;
    errorLogs: AgentErrorLog[];
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

const isCoreAgent = (agentId: string): agentId is CoreAgentId =>
    agentId === 'fundamental_analysis' ||
    agentId === 'financial_news_research' ||
    agentId === 'debate' ||
    agentId === 'technical_analysis';

export const adaptAgentOutput = (
    agentId: string,
    output: StandardAgentOutput | null,
    context = 'agent_output'
): AgentOutputViewModel => {
    const base = buildBaseViewModel(agentId, output);
    if (!isCoreAgent(agentId)) {
        return {
            ...base,
            kind: 'generic',
            preview: parseGenericPreview(output?.preview, `${context}.preview`),
        };
    }

    if (agentId === 'fundamental_analysis') {
        return {
            ...base,
            kind: 'fundamental_analysis',
            preview: parseFundamentalPreviewFromOutput(output, context),
        };
    }
    if (agentId === 'financial_news_research') {
        return {
            ...base,
            kind: 'financial_news_research',
            preview: parseNewsPreviewFromOutput(output, context),
        };
    }
    if (agentId === 'debate') {
        return {
            ...base,
            kind: 'debate',
            preview: parseDebatePreviewFromOutput(output, context),
        };
    }
    return {
        ...base,
        kind: 'technical_analysis',
        preview: parseTechnicalPreviewFromOutput(output, context),
    };
};
