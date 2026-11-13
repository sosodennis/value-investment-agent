"""Filed text observations for conditional execution, without review authority."""

import re
from datetime import date
from html.parser import HTMLParser
from typing import Literal

from pydantic import Field, model_validator

from .arelle_parser import ParsedXbrlFactV1
from .contracts import CanonicalFactV1, QualityStatus, StrictModel
from .facts import CanonicalMappingV1
from .original_issuer import IssuerOperatingSourceV1, fact_matches_original_source
from .serialization import sha256_digest
from .snapshots import SnapshotError

DISCLOSURE_CONCEPTS = (
    "us-gaap:ConsolidationPolicyTextBlock",
    "us-gaap:SegmentReportingDisclosureTextBlock",
)
DISCLOSURE_POLICY: Literal["unreviewed-filed-operating-disclosures-v1"] = (
    "unreviewed-filed-operating-disclosures-v1"
)


def disclosure_policy_digest() -> str:
    return sha256_digest(
        {
            "version": DISCLOSURE_POLICY,
            "concepts": DISCLOSURE_CONCEPTS,
            "source": "latest original at origin; current consolidated annual period",
            "mapping": "exact parser observation scope; provisional without review",
            "use": "filed source reference only; no numeric parameter or suitability claim",
            "authority": "conditional research only; no release or threshold approval",
        }
    )


class ConditionalTransitionDisclosuresV1(StrictModel):
    contract_version: Literal["fundamental.conditional-transition-disclosures.v1"] = (
        "fundamental.conditional-transition-disclosures.v1"
    )
    policy_version: Literal["unreviewed-filed-operating-disclosures-v1"] = (
        DISCLOSURE_POLICY
    )
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_ids: tuple[str, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def pinned_policy(self) -> "ConditionalTransitionDisclosuresV1":
        if self.policy_digest != disclosure_policy_digest():
            raise ValueError("conditional disclosure policy digest differs")
        if self.fact_ids != tuple(sorted(set(self.fact_ids))):
            raise ValueError("disclosure fact IDs must be distinct and ordered")
        return self


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def scoped_operating_text(
    fact: ParsedXbrlFactV1, mapping: CanonicalMappingV1 | None
) -> bool:
    """Allow text only for the explicitly scoped filed operating evidence role."""
    if (
        mapping is None
        or mapping.normalized_field != "filed_operating_evidence"
        or mapping.source_concept not in DISCLOSURE_CONCEPTS
        or fact.concept != mapping.source_concept
        or mapping.observation_scope is None
        or sha256_digest(fact) not in mapping.observation_scope.observation_digests
        or fact.is_numeric
        or fact.unit is not None
        or fact.dimensions
        or fact.consolidation_scope != "consolidated"
        or fact.entity_scheme != "http://www.sec.gov/CIK"
        or not re.fullmatch(
            r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?",
            fact.namespace_uri or "",
        )
        or fact.period_start is None
        or fact.period_end is None
        or fact.instant is not None
        or not 300 <= (fact.period_end - fact.period_start).days <= 380
    ):
        return False
    text = _Text()
    text.feed(fact.value)
    return any(character.isalpha() for character in " ".join(text.parts))


def conditional_transition_disclosures(
    proof: ConditionalTransitionDisclosuresV1,
    *,
    facts: tuple[CanonicalFactV1, ...],
    mappings: tuple[CanonicalMappingV1, ...],
    source: IssuerOperatingSourceV1,
    period_start: date,
    period_end: date,
) -> tuple[CanonicalFactV1, ...]:
    """Check source references without authenticating accounting or suitability."""
    evidence = tuple(
        f for f in facts if f.normalized_field == "filed_operating_evidence"
    )
    latest_at = max(original.source.available_at for original in source.originals)
    latest = tuple(o for o in source.originals if o.source.available_at == latest_at)
    if (
        len(latest) != 1
        or latest[0].report_period_end != period_end
        or tuple(sorted(f.fact_id for f in evidence)) != proof.fact_ids
        or sorted(f.concept for f in evidence) != sorted(DISCLOSURE_CONCEPTS)
    ):
        raise SnapshotError(
            "CONDITIONAL_TRANSITION_DISCLOSURES_INVALID",
            "both distinct operating disclosures must bind the latest decision original",
        )
    original = latest[0]
    by_mapping = {mapping.decision_id: mapping for mapping in mappings}
    for fact in evidence:
        mapping = by_mapping.get(fact.mapping_decision_id or "")
        observations = (
            tuple(
                observation
                for observation in original.report.facts
                if scoped_operating_text(observation, mapping)
            )
            if mapping is not None
            else ()
        )
        if (
            mapping is None
            or mapping.status != "provisional"
            or mapping.reviewer is not None
            or mapping.reviewed_at is not None
            or len(observations) != 1
            or fact.value != observations[0].value
            or fact.quality is not QualityStatus.PROVISIONAL
            or not fact_matches_original_source(fact, source)
            or fact.source.content_hash != original.source.content_hash
            or fact.issuer_id != source.identity.issuer_id
            or fact.available_at > source.valuation_timestamp
            or fact.period_start != period_start
            or fact.period_end != period_end
            or fact.unit != "text"
            or fact.context.dimensions
        ):
            raise SnapshotError(
                "CONDITIONAL_TRANSITION_DISCLOSURES_INVALID",
                "conditional operating text must reproduce its unreviewed original mapping",
            )
    return tuple(sorted(evidence, key=lambda fact: fact.fact_id))
