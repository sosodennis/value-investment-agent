from src.agents.debate.domain.models import EvidenceFact
from src.agents.debate.domain.validators import FactValidator


def test_fact_extraction_regex():
    text = "Revenue grew 20% [Fact:F001] and sentiment is positive [Fact:N005]."
    citations = FactValidator.extract_citations(text)
    assert citations == ["[Fact:F001]", "[Fact:N005]"]


def test_citation_validation():
    valid_facts = [
        EvidenceFact(
            fact_id="F001",
            source_type="financials",
            source_weight="HIGH",
            summary="F1",
            provenance={"description": "test"},
        ),
        EvidenceFact(
            fact_id="N005",
            source_type="news",
            source_weight="MEDIUM",
            summary="N1",
            provenance={"description": "test"},
        ),
    ]

    text = "Claim [Fact:F001] and invalid [Fact:F999]"
    results = FactValidator.validate_citations(text, valid_facts)

    assert results["total_cited"] == 2
    assert "F001" in results["valid_citations"]
    assert "F999" in results["invalid_citations"]


def test_compliance():
    text = "I like [Fact:F001], [Fact:F002], [Fact:F003]"
    assert FactValidator.check_compliance(text, "bull") is True

    text = "Short it [Fact:N001]"
    assert FactValidator.check_compliance(text, "bear") is False  # Needs 2

    text = "Short it [Fact:N001], [Fact:F001]"
    assert FactValidator.check_compliance(text, "bear") is True
