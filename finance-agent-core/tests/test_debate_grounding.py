from src.agents.debate.domain.models import EvidenceFact
from src.agents.debate.domain.validators import FactValidator
from src.shared.kernel.traceable import ManualProvenance


def test_fact_extraction_regex():
    text = (
        "Revenue grew 20% [Fact:F001], sentiment is positive [Fact:N005], "
        "and valuation upside is high [Fact:V003]."
    )
    citations = FactValidator.extract_citations(text)
    assert citations == ["[Fact:F001]", "[Fact:N005]", "[Fact:V003]"]


def test_citation_validation():
    valid_facts = [
        EvidenceFact(
            fact_id="F001",
            source_type="financials",
            source_weight="HIGH",
            summary="F1",
            provenance=ManualProvenance(description="test"),
        ),
        EvidenceFact(
            fact_id="N005",
            source_type="news",
            source_weight="MEDIUM",
            summary="N1",
            provenance=ManualProvenance(description="test"),
        ),
        EvidenceFact(
            fact_id="V003",
            source_type="valuation",
            source_weight="HIGH",
            summary="V1",
            provenance=ManualProvenance(description="test"),
        ),
    ]

    text = "Claim [Fact:F001] [Fact:V003] and invalid [Fact:F999]"
    results = FactValidator.validate_citations(text, valid_facts)

    assert results["total_cited"] == 3
    assert "F001" in results["valid_citations"]
    assert "V003" in results["valid_citations"]
    assert "F999" in results["invalid_citations"]


def test_compliance():
    text = "I like [Fact:F001], [Fact:F002], [Fact:F003]"
    assert FactValidator.check_compliance(text, "bull") is True

    text = "Short it [Fact:N001]"
    assert FactValidator.check_compliance(text, "bear") is False  # Needs 2

    text = "Short it [Fact:N001], [Fact:F001]"
    assert FactValidator.check_compliance(text, "bear") is True
