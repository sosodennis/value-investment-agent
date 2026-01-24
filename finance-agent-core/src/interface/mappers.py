"""
Output Mappers - Transform Graph State to UI Protocol

This module implements the Backend-for-Frontend (BFF) pattern, transforming
nested LangGraph state structures into flat, UI-ready payloads.

Design Principles:
1. Agents own their state structure (nested, context-rich)
2. Frontend owns its prop interface (flat, component-focused)
3. Mappers bridge the gap without polluting either side
"""


class NodeOutputMapper:
    """
    Centralized mapper for transforming agent outputs to UI payloads.

    Each method corresponds to a high-level agent and knows how to extract
    the relevant data from that agent's nested state structure.
    """

    @staticmethod
    def _merge_standard_fields(payload: dict, output: dict) -> dict:
        """Helper to merge standard fields (node_statuses, messages) into the payload."""
        if payload is None:
            return None

        # Preserve keys if they exist in the raw output
        for key in ["node_statuses", "messages", "ticker"]:
            if key in output and output[key] is not None:
                payload[key] = output[key]
        return payload

    @staticmethod
    def map_technical_analysis(output: dict) -> dict | None:
        """
        Transform Technical Analysis state to UI payload.

        Input:  {"technical_analysis": {"output": {...}}}
        Output: {...} (flattened TechnicalSignal)
        """
        if not isinstance(output, dict):
            return None

        # Navigate nested structure
        ta_context = output.get("technical_analysis", {})
        if isinstance(ta_context, dict):
            ta_output = ta_context.get("output")
            if isinstance(ta_output, dict):
                return NodeOutputMapper._merge_standard_fields(ta_output, output)

        return None

    @staticmethod
    def map_fundamental_analysis(output: dict) -> dict | None:
        """
        Transform Fundamental Analysis state to UI payload.

        Input:  {"fundamental": {"analysis_output": {...}}}
        Output: {...} (flattened analysis)
        """
        if not isinstance(output, dict):
            return None

        fundamental_context = output.get("fundamental", {})
        if isinstance(fundamental_context, dict):
            analysis_output = fundamental_context.get("analysis_output")
            if isinstance(analysis_output, dict):
                return NodeOutputMapper._merge_standard_fields(analysis_output, output)

        return None

    @staticmethod
    def map_financial_news(output: dict) -> dict | None:
        """
        Transform Financial News state to UI payload.

        Input:  {"financial_news": {"output": {...}}}
        Output: {...} (NewsResearchOutput with news_items)
        """
        if not isinstance(output, dict):
            return None

        news_context = output.get("financial_news", {})
        if isinstance(news_context, dict):
            news_output = news_context.get("output")
            if isinstance(news_output, dict):
                return NodeOutputMapper._merge_standard_fields(news_output, output)

        return None

    @staticmethod
    def map_debate(output: dict) -> dict | None:
        """
        Transform Debate state to UI payload.

        Input:  {"debate": {"conclusion": {...}}}
        Output: {"conclusion": {...}}
        """
        if not isinstance(output, dict):
            return None

        debate_context = output.get("debate", {})
        if isinstance(debate_context, dict):
            conclusion = debate_context.get("conclusion")
            if conclusion:
                return NodeOutputMapper._merge_standard_fields(
                    {"conclusion": conclusion}, output
                )

        return None

    @staticmethod
    def map_intent_extraction(output: dict) -> dict | None:
        """
        Transform Intent Extraction state to UI payload.

        Input:  {"intent_extraction": {...}}
        Output: {...} (intent context)
        """
        if not isinstance(output, dict):
            return None

        intent_context = output.get("intent_extraction")
        if isinstance(intent_context, dict):
            return NodeOutputMapper._merge_standard_fields(intent_context, output)

        return None

    @classmethod
    def transform(cls, agent_id: str, output: dict) -> dict | None:
        """
        Route to appropriate mapper based on agent_id.

        Args:
            agent_id: The high-level agent identifier
            output: The raw graph state output (potentially nested)

        Returns:
            Flattened UI payload or None if no mapping exists
        """
        mapper_registry = {
            "technical_analysis": cls.map_technical_analysis,
            "fundamental_analysis": cls.map_fundamental_analysis,
            "financial_news_research": cls.map_financial_news,
            "debate": cls.map_debate,
            "intent_extraction": cls.map_intent_extraction,
        }

        mapper = mapper_registry.get(agent_id)
        if mapper:
            return mapper(output)

        # For unmapped agents, return output as-is (backward compatibility)
        return output if isinstance(output, dict) else None
