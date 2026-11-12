"""Release-bound award and quote evidence consumed by the formal composer."""

from collections.abc import Iterable
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import Field

from .contracts import CanonicalFactV1, QualityStatus, SourceRole, SourceSnapshotV1
from .data_releases import DataReleaseManifestV1
from .equity_dilution import (
    CommonShareQuoteV1,
    DilutionError,
    DilutionModel,
    EquityAwardInventoryV1,
    PerformanceStockAwardV1,
    TreasuryStockPolicyV1,
    _award_facts,
)
from .facts import canonical_fact_digest
from .quote_sources import verify_quote_source
from .serialization import canonical_bytes, sha256_digest

EQUITY_DILUTION_ARTIFACT_ROLE: Literal["equity-dilution-evidence-v1"] = (
    "equity-dilution-evidence-v1"
)
AWARD_FACT_FIELDS = (
    "equity_award_quantity",
    "equity_award_unrecognized_compensation",
    "equity_award_exercise_price",
)
EQUITY_QUOTE_SOURCE_ROLE = "equity-dilution-quote-source-v1"


class EquityDilutionEvidenceV1(DilutionModel):
    protocol: Literal["equity-dilution-evidence-v1"] = EQUITY_DILUTION_ARTIFACT_ROLE
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    inventory: EquityAwardInventoryV1
    quote: CommonShareQuoteV1
    policy: TreasuryStockPolicyV1

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def facts(self) -> tuple[CanonicalFactV1, ...]:
        return tuple(
            fact for award in self.inventory.instruments for fact in _award_facts(award)
        )


class DilutionArtifactReader(Protocol):
    def read(self, artifact_id: str) -> bytes: ...


def verify_dilution_fact_bindings(
    evidence: EquityDilutionEvidenceV1,
    *,
    snapshot: SourceSnapshotV1,
    released_facts: Iterable[CanonicalFactV1],
) -> None:
    """Require inventory observations to be the exact reviewed release facts."""
    identity = snapshot.identity
    if (
        evidence.snapshot_manifest_digest != snapshot.manifest_digest
        or evidence.inventory.issuer_id != identity.issuer_id
        or evidence.inventory.security_id != identity.security_id
        or evidence.inventory.currency != identity.currency
        or evidence.quote.issuer_id != identity.issuer_id
        or evidence.quote.security_id != identity.security_id
    ):
        raise DilutionError(
            "DILUTION_SNAPSHOT_MISMATCH",
            "award evidence belongs to a different snapshot or identity",
        )
    declared = {fact.fact_id: fact for fact in released_facts}
    if {
        fact.fact_id
        for fact in declared.values()
        if fact.normalized_field in AWARD_FACT_FIELDS
    } != {fact.fact_id for fact in evidence.facts}:
        raise DilutionError(
            "DILUTION_INVENTORY_INCOMPLETE",
            "reviewed inventory must retain every released award observation",
        )
    sources = {
        source.content_hash
        for source in snapshot.source_records
        if source.role is SourceRole.FILING
        and source.available_at <= snapshot.valuation_timestamp
    }
    traces = (
        evidence.inventory.coverage_evidence,
        *(
            award.condition_evidence
            for award in evidence.inventory.instruments
            if isinstance(award, PerformanceStockAwardV1)
        ),
    )
    if any(
        not trace.source_refs or not set(trace.source_refs) <= sources
        for trace in traces
    ):
        raise DilutionError(
            "DILUTION_REVIEW_SOURCE_MISMATCH",
            "inventory coverage and award conditions must cite available original sources in the snapshot",
        )
    for award in evidence.inventory.instruments:
        for index, fact in enumerate(_award_facts(award)):
            expected_role = (
                "equity_award_quantity"
                if index == 0
                else "equity_award_unrecognized_compensation"
                if fact is award.unrecognized_compensation
                else "equity_award_exercise_price"
            )
            released = declared.get(fact.fact_id)
            if (
                released is None
                or fact.quality is not QualityStatus.VERIFIED
                or fact.normalized_field != expected_role
                or fact.source.content_hash not in sources
                or canonical_fact_digest(fact) != canonical_fact_digest(released)
            ):
                raise DilutionError(
                    "DILUTION_RELEASE_FACT_MISMATCH",
                    "award evidence must bind exact reviewed source facts in the pinned release",
                )


def load_release_dilution_evidence(
    manifest: DataReleaseManifestV1,
    *,
    snapshot: SourceSnapshotV1,
    artifacts: DilutionArtifactReader,
    released_facts: Iterable[CanonicalFactV1],
) -> EquityDilutionEvidenceV1 | None:
    """Read immutable signed-release artifacts; never obtain external evidence."""
    matches = []
    for reference in sorted(manifest.artifact_refs, key=lambda item: item.artifact_id):
        if reference.role != EQUITY_DILUTION_ARTIFACT_ROLE:
            continue
        raw = artifacts.read(reference.artifact_id)
        if (
            reference.media_type != "application/json"
            or sha256(raw).hexdigest() != reference.content_hash
        ):
            raise DilutionError(
                "DILUTION_ARTIFACT_MISMATCH",
                "award artifact differs from the pinned release",
            )
        evidence = EquityDilutionEvidenceV1.model_validate_json(raw)
        if canonical_bytes(evidence) != raw:
            raise DilutionError(
                "DILUTION_ARTIFACT_NONCANONICAL",
                "award evidence requires canonical serialization",
            )
        if evidence.snapshot_manifest_digest == snapshot.manifest_digest:
            matches.append(evidence)
    if not matches:
        return None
    if len(matches) != 1:
        raise DilutionError(
            "DILUTION_ARTIFACT_AMBIGUOUS",
            "release declares conflicting award evidence for the snapshot",
        )
    evidence = matches[0]
    verify_dilution_fact_bindings(
        evidence, snapshot=snapshot, released_facts=released_facts
    )
    quote_reference = next(
        (
            ref
            for ref in manifest.artifact_refs
            if ref.role == EQUITY_QUOTE_SOURCE_ROLE
            and ref.content_hash == evidence.quote.content_hash
        ),
        None,
    )
    if quote_reference is None:
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_UNAVAILABLE",
            "reviewed quote source bytes are unavailable",
        )
    raw_quote = artifacts.read(quote_reference.artifact_id)
    if sha256(raw_quote).hexdigest() != evidence.quote.content_hash:
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_MISMATCH",
            "quote source bytes differ from the reviewed evidence",
        )
    verify_quote_source(evidence.quote, raw_quote)
    return evidence
