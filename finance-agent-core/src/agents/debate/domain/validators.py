import re

from .models import EvidenceFact


class FactValidator:
    """
    Enforces grounding by validating [Fact:ID] citations in debate transcripts.
    """

    @staticmethod
    def extract_citations(text: str) -> list[str]:
        """Extracts all [Fact:ID] tags from text."""
        return re.findall(r"\[Fact:[FNT]\d{3}\]", text)

    @staticmethod
    def validate_citations(text: str, valid_facts: list[EvidenceFact]) -> dict:
        """
        Validates that all cited Fact IDs exist in the registry.
        Returns a report with valid, invalid, and missing citations.
        """
        valid_ids = {f.fact_id for f in valid_facts}
        cited_tags = re.findall(r"\[Fact:([A-Z0-9]+)\]", text)

        results = {
            "total_cited": len(cited_tags),
            "valid_citations": [],
            "invalid_citations": [],
            "missing_registry": False,
        }

        for fact_id in cited_tags:
            if fact_id in valid_ids:
                results["valid_citations"].append(fact_id)
            else:
                results["invalid_citations"].append(fact_id)

        return results

    @staticmethod
    def check_compliance(text: str, role: str) -> bool:
        """
        Basic heuristic check for prompt compliance.
        Bull: >= 3 Financial facts.
        Bear: >= 2 challenge points.
        """
        cited_ids = re.findall(r"\[Fact:([FNT]\d{3})\]", text)
        financial_citations = [fid for fid in cited_ids if fid.startswith("F")]

        if role == "bull":
            return len(financial_citations) >= 3
        if role == "bear":
            # For Bear, we generally check for any evidence or specifically 2 points in current prompts
            return len(cited_ids) >= 2

        return len(cited_ids) > 0
