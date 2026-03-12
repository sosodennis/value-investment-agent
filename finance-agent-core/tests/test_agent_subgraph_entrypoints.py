from src.agents.debate.subgraph import build_debate_subgraph
from src.agents.fundamental.application.subgraph import build_fundamental_subgraph
from src.agents.intent.application.subgraph import build_intent_extraction_subgraph
from src.agents.news.subgraph import build_financial_news_subgraph
from src.agents.technical.application.subgraph import build_technical_subgraph


def test_agent_subgraph_entrypoints_compile() -> None:
    graphs = [
        build_intent_extraction_subgraph(),
        build_fundamental_subgraph(),
        build_financial_news_subgraph(),
        build_technical_subgraph(),
        build_debate_subgraph(),
    ]

    assert all(hasattr(graph, "invoke") for graph in graphs)
