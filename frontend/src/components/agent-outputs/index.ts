import { FundamentalAnalysisOutput } from './FundamentalAnalysisOutput';
import { NewsResearchOutput } from './NewsResearchOutput';
import { DebateOutput } from './DebateOutput';
import { TechnicalAnalysisOutput } from './TechnicalAnalysisOutput';
import { GenericAgentOutput } from './GenericAgentOutput';

export * from './GenericAgentOutput';
export * from './FundamentalAnalysisOutput';
export * from './NewsResearchOutput';
export * from './DebateOutput';
export * from './TechnicalAnalysisOutput';

export const AGENT_OUTPUT_COMPONENTS: Record<string, React.ComponentType<any>> = {
    fundamental_analysis: FundamentalAnalysisOutput,
    financial_news_research: NewsResearchOutput,
    debate: DebateOutput,
    technical_analysis: TechnicalAnalysisOutput,
    // Fallback or generic agents can use GenericAgentOutput directly or be mapped here
    default: GenericAgentOutput
};
