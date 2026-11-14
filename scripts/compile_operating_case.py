"""Compile explicit original/mapping plans through the formal operating boundary."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from fundamental_service.accounting_fields import (
    AccountingFieldExtractionV1,
    AccountingFieldRequestV1,
    extract_accounting_fields,
)
from fundamental_service.contracts import QualityStatus, StrictModel
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.operating_disclosures import ConditionalTransitionDisclosuresV1
from fundamental_service.operating_label_contracts import (
    ConditionalLabelRequestV1,
    OperatingComparisonRequestV1,
    OriginalAnnualTargetV1,
    operating_label_policy_digest,
)
from fundamental_service.operating_scenario_contracts import (
    OperatingScenarioRequestV1,
    OperatingScenarioV1,
    ScenarioObservationSetV1,
    ScenarioPeriodCalendarV1,
    UNRESOLVED_CLASSES,
    BASELINE_SOURCE_POLICY,
    scenario_policy_digest,
)
from fundamental_service.operating_scenarios import select_scenario_periods
from fundamental_service.original_issuer import (
    OriginalIssuerEvidenceV1,
    compose_issuer_operating_source,
    fact_matches_operating_identity,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError

from export_history_study_evidence import runtime_pins
from plan_history_study_precision import ROOT, DesignError, digest, publish_report


class ObservationPlan(StrictModel):
    originals: tuple[OriginalIssuerEvidenceV1, ...] = Field(min_length=1)
    valuation_timestamp: datetime
    mapping_version: str = Field(min_length=1)
    mappings: tuple[CanonicalMappingV1, ...] = Field(min_length=1)
    calendars: tuple[ScenarioPeriodCalendarV1, ...] = Field(min_length=2, max_length=5)
    scenarios: tuple[OperatingScenarioV1, ...] = Field(min_length=1, max_length=1000)
    source_selection_policy: Literal[
        "latest-complete-original-per-period-v1",
        "latest-complete-original-per-baseline-family-v2",
    ] = "latest-complete-original-per-period-v1"
    scope_assumptions: tuple[str, ...] = Field(min_length=1)
    scope_evidence_digests: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_provisional_scope(self) -> ObservationPlan:
        if any(
            mapping.status != "provisional"
            or mapping.mapping_version != self.mapping_version
            or (mapping.observation_scope is None and mapping.accounting_rules is None)
            for mapping in self.mappings
        ):
            raise ValueError("compiler requires provisional source-bound mappings")
        if any(len(text.strip()) < 40 for text in self.scope_assumptions):
            raise ValueError(
                "accounting scope requires explicit substantive assumptions"
            )
        if len({m.decision_id for m in self.mappings}) != len(self.mappings):
            raise ValueError("mapping identities must be unique")
        return self


class CasePlan(StrictModel):
    schema_version: Literal["operating-case-plan.v1"] = "operating-case-plan.v1"
    decision: ObservationPlan
    label: ObservationPlan
    filing_inventory: tuple[OriginalAnnualTargetV1, ...] = Field(min_length=1)
    inventory_evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_versions: dict[Literal["fcff_dcf", "transition_fcff_dcf"], str]
    protocol_version: str = Field(min_length=1)
    transition_disclosures: ConditionalTransitionDisclosuresV1 | None = None


def compile_observations(
    plan: ObservationPlan,
) -> tuple[ScenarioObservationSetV1, tuple[AccountingFieldExtractionV1, ...]]:
    """Retain all candidates in packets; pass only issuer observations onward."""
    source = compose_issuer_operating_source(
        plan.originals, valuation_timestamp=plan.valuation_timestamp
    )
    mappings = tuple(sorted(plan.mappings, key=lambda m: m.decision_id))
    extractions = tuple(
        extract_accounting_fields(
            AccountingFieldRequestV1(
                original=original,
                normalized_fields=tuple(sorted({m.normalized_field for m in mappings})),
                mapping_version=plan.mapping_version,
                mappings=mappings,
            )
        )
        for original in source.originals
    )
    if any(row.extraction_failures for packet in extractions for row in packet.fields):
        raise DesignError(
            "mapping extraction failure must be resolved before compilation"
        )
    facts = {
        fact.fact_id: fact
        for packet in extractions
        for row in packet.fields
        for candidate in row.candidates
        for fact in (candidate.canonical_fact(quality=QualityStatus.PROVISIONAL),)
        if fact_matches_operating_identity(fact, source)
    }
    observations = ScenarioObservationSetV1(
        source=source,
        facts=tuple(facts[key] for key in sorted(facts)),
        mapping_version=plan.mapping_version,
        mapping_manifest_digest=sha256_digest(mappings),
        mappings=mappings,
        source_selection_policy=plan.source_selection_policy,
    )
    return observations, extractions


def compile_case(plan: CasePlan) -> dict[str, object]:
    plan = CasePlan.model_validate_json(canonical_bytes(plan))
    decision_set, decision_packets = compile_observations(plan.decision)
    label_set, label_packets = compile_observations(plan.label)
    baseline = plan.decision.source_selection_policy == BASELINE_SOURCE_POLICY
    policy: Literal[
        "baseline-unconsumed-capex-v2", "nonnegative-parent-partitions-v1"
    ] = (
        "baseline-unconsumed-capex-v2"
        if baseline
        else "nonnegative-parent-partitions-v1"
    )

    def assumptions(item: ObservationPlan) -> tuple[str, ...]:
        return tuple(
            sorted(
                {*item.scope_evidence_digests, sha256_digest(item.scope_assumptions)}
            )
        )

    decision = OperatingScenarioRequestV1(
        **decision_set.model_dump(),
        contract_version="fundamental.operating-scenarios.v2"
        if baseline
        else "fundamental.operating-scenarios.v1",
        periods=select_scenario_periods(decision_set, plan.decision.calendars),
        scenarios=plan.decision.scenarios,
        protocol_version=plan.protocol_version,
        policy_version=policy,
        policy_digest=scenario_policy_digest(policy),
        model_versions=plan.model_versions,
        scope_assumption_evidence_digests=assumptions(plan.decision),
        unresolved_classes=UNRESOLVED_CLASSES,
        transition_disclosures=plan.transition_disclosures,
    )
    label = ConditionalLabelRequestV1(
        **label_set.model_dump(),
        periods=select_scenario_periods(label_set, plan.label.calendars),
        scenarios=plan.label.scenarios,
        scope_assumption_evidence_digests=assumptions(plan.label),
        unresolved_classes=UNRESOLVED_CLASSES,
    )
    request = OperatingComparisonRequestV1(
        contract_version="fundamental.operating-comparison.v2"
        if baseline
        else "fundamental.operating-comparison.v1",
        decision=decision,
        decision_input_digest=sha256_digest(decision),
        label=label,
        filing_inventory=plan.filing_inventory,
        filing_inventory_digest=sha256_digest(plan.filing_inventory),
        inventory_evidence_digest=plan.inventory_evidence_digest,
        protocol_version=plan.protocol_version,
        policy_digest=operating_label_policy_digest(),
    )
    return {
        "request": request,
        "plan_digest": sha256_digest(plan),
        "decision_extractions": decision_packets,
        "label_extractions": label_packets,
        "excluded_nonissuer_candidates": {
            kind: tuple(
                sorted(
                    candidate.candidate_id
                    for packet in packets
                    for row in packet.fields
                    for candidate in row.candidates
                    if candidate.candidate_id
                    not in {fact.fact_id for fact in observations.facts}
                )
            )
            for kind, packets, observations in (
                ("decision", decision_packets, decision_set),
                ("label", label_packets, label_set),
            )
        },
        "accounting_assumptions": {
            "decision": plan.decision.scope_assumptions,
            "label": plan.label.scope_assumptions,
        },
        "authority": "provisional_observations_only_no_mapping_review_or_release",
        "supported_history_threshold": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--exact-commit", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if head != args.exact_commit or subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ):
            raise DesignError("exact clean implementation commit is required")
        raw = args.plan.read_bytes()
        if digest(raw) != args.plan_digest:
            raise DesignError("case plan content digest differs")
        plan = CasePlan.model_validate_json(raw)
        if canonical_bytes(plan) != raw:
            raise DesignError("case plan must use canonical serialization")
        output = compile_case(plan)
        inputs = {
            "exact_commit": head,
            "runtime": runtime_pins(),
            "plan_digest": args.plan_digest,
        }
        report = {
            "inputs": inputs,
            "input_digest": sha256_digest(inputs),
            "output": output,
            "output_digest": sha256_digest(output),
        }
        receipt = publish_report(
            args.output_directory, json.loads(canonical_bytes(report))
        )
        print(
            json.dumps(
                {
                    **receipt,
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                },
                sort_keys=True,
            )
        )
    except (
        OSError,
        ValueError,
        ArithmeticError,
        SnapshotError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(
            2,
            canonical_bytes(
                {
                    "error_code": error.code
                    if isinstance(error, SnapshotError)
                    else "OPERATING_CASE_INVALID",
                    "message": str(error),
                }
            ).decode()
            + "\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
