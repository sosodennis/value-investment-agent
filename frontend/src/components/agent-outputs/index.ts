/**
 * Agent Output Component Registry
 * Using Barrel Pattern for simplified imports in the Main Panel.
 */

export { FundamentalAnalysisOutput } from './FundamentalAnalysisOutput';
export { NewsResearchOutput } from './NewsResearchOutput';
export { DebateOutput } from './DebateOutput';
export { TechnicalAnalysisOutput } from './TechnicalAnalysisOutput';
export { GenericAgentOutput } from './GenericAgentOutput';

import { FundamentalAnalysisOutput } from './FundamentalAnalysisOutput';
import { NewsResearchOutput } from './NewsResearchOutput';
import { DebateOutput } from './DebateOutput';
import { TechnicalAnalysisOutput } from './TechnicalAnalysisOutput';
import { GenericAgentOutput } from './GenericAgentOutput';

export const AGENT_OUTPUT_COMPONENTS: Record<string, React.ComponentType<any>> = {
    fundamental_analysis: FundamentalAnalysisOutput,
    financial_news_research: NewsResearchOutput,
    debate: DebateOutput,
    technical_analysis: TechnicalAnalysisOutput,
    default: GenericAgentOutput
};
