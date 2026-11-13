"""Add an original-bound older period without changing existing research inputs."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from fundamental_service.contracts import CanonicalFactV1, QualityStatus, StrictModel
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.operating_label_contracts import OperatingComparisonRequestV1
from fundamental_service.operating_scenario_contracts import (
    CORE_FIELDS,
    PARENT_CONCEPTS,
    ScenarioPeriodV1,
)
from fundamental_service.operating_scenarios import resolve_scenario_observations
from fundamental_service.original_issuer import (
    OriginalIssuerEvidenceV1,
    compose_issuer_operating_source,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest

from analyze_history_study import ROOT, DesignError
from export_history_study_evidence import FileReference, read_evidence, runtime_pins
from plan_history_study_precision import digest, publish_report


class ExtendedScenario(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    parent_scenario_id: str
    older_continuing_capex_fraction: Decimal = Field(ge=0, le=1, allow_inf_nan=False)


class SeedExtension(StrictModel):
    schema_version: Literal["history-study-seed-extension.v1"]
    original: OriginalIssuerEvidenceV1
    mappings: tuple[CanonicalMappingV1, ...] = Field(min_length=9, max_length=9)
    fiscal_year: int
    period_start: date
    period_end: date
    mapping_version: str = Field(min_length=1)
    scenarios: tuple[ExtendedScenario, ...] = Field(min_length=1, max_length=1000)
    scope_assumptions: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_unreviewed_observations(self) -> SeedExtension:
        if {m.normalized_field for m in self.mappings} != {
            *CORE_FIELDS,
            *PARENT_CONCEPTS,
        } or len({m.decision_id for m in self.mappings}) != len(self.mappings):
            raise ValueError(
                "one distinct mapping for every core/parent role is required"
            )
        if any(m.status != "provisional" for m in self.mappings):
            raise ValueError("an extension cannot grant mapping approval")
        if (
            self.period_end.year != self.fiscal_year
            or not 300 <= (self.period_end - self.period_start).days <= 380
            or any(len(text.strip()) < 20 for text in self.scope_assumptions)
        ):
            raise ValueError(
                "aligned annual dates and explicit scope assumptions required"
            )
        if len({s.scenario_id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("extension scenario identities must be unique")
        return self


def compile_seed(
    seed: OperatingComparisonRequestV1, extension: SeedExtension
) -> OperatingComparisonRequestV1:
    """Rebind mappings through the formal mapper; perform no forecast or formula."""
    decision = seed.decision
    if (
        len(decision.periods) >= 5
        or extension.fiscal_year != decision.periods[0].fiscal_year - 1
        or extension.period_end.toordinal() + 1
        != decision.periods[0].period_start.toordinal()
    ):
        raise DesignError("extension must add exactly the immediately preceding year")
    if extension.mapping_version == decision.mapping_version:
        raise DesignError("an extended manifest requires a new mapping version")
    if extension.original.source.accession_number in {
        original.source.accession_number for original in decision.source.originals
    }:
        raise DesignError("extension original must be distinct from retained originals")
    parents = {scenario.scenario_id: scenario for scenario in decision.scenarios}
    if {item.parent_scenario_id for item in extension.scenarios} != set(parents):
        raise DesignError("every prior scenario must be retained without substitution")
    source = compose_issuer_operating_source(
        (*decision.source.originals, extension.original),
        valuation_timestamp=decision.source.valuation_timestamp,
    )
    # Validate old evidence before remapping. Rebinding cannot repair bad input.
    resolve_scenario_observations(decision, decision.periods)
    originals = {item.source.content_hash: item for item in source.originals}
    old_mappings = (*decision.mappings, *extension.mappings)
    if len({m.decision_id for m in old_mappings}) != len(old_mappings):
        raise DesignError("extension mapping IDs collide with retained mappings")
    rebound: dict[str, CanonicalMappingV1] = {}
    for old in old_mappings:
        payload = old.model_dump(mode="json", exclude={"decision_id"})
        payload["mapping_version"] = extension.mapping_version
        payload["decision_id"] = "mapping-" + sha256_digest(payload)
        rebound[old.decision_id] = CanonicalMappingV1.model_validate_json(
            canonical_bytes(payload)
        )

    def mapped(
        source_hash: str, mapping_id: str, quality: QualityStatus
    ) -> tuple[CanonicalFactV1, ...]:
        original = originals[source_hash]
        mapping = rebound[mapping_id]
        return tuple(
            candidate.canonical_fact(quality=quality)
            for candidate in parsed_facts_to_candidates(
                original.report,
                source=original.source,
                issuer_id=source.identity.issuer_id,
                normalized_field=mapping.normalized_field,
                mapping=mapping,
            )
        )

    def financial_identity(fact: CanonicalFactV1) -> dict[str, object]:
        return fact.model_dump(exclude={"fact_id", "mapping_decision_id"})

    facts = []
    identifiers = {}
    for old_fact in decision.facts:
        matches = tuple(
            fact
            for fact in mapped(
                old_fact.source.content_hash,
                old_fact.mapping_decision_id or "",
                old_fact.quality,
            )
            if financial_identity(fact) == financial_identity(old_fact)
        )
        if len(matches) != 1:
            raise DesignError("retained financial identity does not reproduce")
        facts.append(matches[0])
        identifiers[old_fact.fact_id] = matches[0].fact_id
    added = {}
    for mapping in extension.mappings:
        matches = mapped(
            extension.original.source.content_hash,
            mapping.decision_id,
            QualityStatus.PROVISIONAL,
        )
        if len(matches) != 1 or matches[0].period_end != extension.period_end:
            raise DesignError(
                "older mapping must select one source-bound period observation"
            )
        added[mapping.normalized_field] = matches[0].fact_id
        facts.append(matches[0])
    periods = (
        ScenarioPeriodV1(
            fiscal_year=extension.fiscal_year,
            period_start=extension.period_start,
            period_end=extension.period_end,
            fact_ids=added,
        ),
        *(
            period.model_copy(
                update={
                    "fact_ids": {
                        role: identifiers[fact_id]
                        for role, fact_id in period.fact_ids.items()
                    }
                }
            )
            for period in decision.periods
        ),
    )
    scenarios = tuple(
        parents[item.parent_scenario_id].model_copy(
            update={
                "scenario_id": item.scenario_id,
                "continuing_capex_fractions": {
                    extension.fiscal_year: item.older_continuing_capex_fraction,
                    **parents[item.parent_scenario_id].continuing_capex_fractions,
                },
            }
        )
        for item in sorted(extension.scenarios, key=lambda item: item.scenario_id)
    )
    mappings = tuple(sorted(rebound.values(), key=lambda mapping: mapping.decision_id))
    extended = decision.model_copy(
        update={
            "source": source,
            "facts": tuple(sorted(facts, key=lambda fact: fact.fact_id)),
            "periods": periods,
            "scenarios": scenarios,
            "mapping_version": extension.mapping_version,
            "mappings": mappings,
            "mapping_manifest_digest": sha256_digest(mappings),
            "scope_assumption_evidence_digests": tuple(
                sorted(
                    {
                        *decision.scope_assumption_evidence_digests,
                        sha256_digest(extension),
                    }
                )
            ),
        }
    )
    result = OperatingComparisonRequestV1.model_validate_json(
        canonical_bytes(
            seed.model_copy(
                update={
                    "decision": extended,
                    "decision_input_digest": sha256_digest(extended),
                }
            )
        )
    )
    resolve_scenario_observations(result.decision, result.decision.periods)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("seed", "extension", "output-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if head != args.exact_commit or subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ):
            raise DesignError("exact clean implementation commit is required")
        raw_seed = args.seed.read_bytes()
        raw_extension = args.extension.read_bytes()
        for path, raw in ((args.seed, raw_seed), (args.extension, raw_extension)):
            read_evidence(
                FileReference(path=str(path.resolve()), sha256=digest(raw)), ROOT
            )
        seed = OperatingComparisonRequestV1.model_validate_json(raw_seed)
        extension = SeedExtension.model_validate_json(raw_extension)
        result = compile_seed(seed, extension)
        inputs = {
            "issue": 376,
            "exact_commit": head,
            "seed_digest": digest(raw_seed),
            "extension_digest": digest(raw_extension),
            "runtime": runtime_pins(),
            "tool_digest": digest(Path(__file__).read_bytes()),
        }
        output = {
            "request_digest": sha256_digest(result),
            "fiscal_years": [period.fiscal_year for period in result.decision.periods],
            "fact_count": len(result.decision.facts),
            "mapping_manifest_digest": result.decision.mapping_manifest_digest,
            "scenario_count": len(result.decision.scenarios),
            "label_digest": sha256_digest(result.label),
            "authority": "unreviewed_conditional_arithmetic_not_trusted_release",
            "complete_exact_study_cases": 0,
            "supported_history_threshold": None,
        }
        report = {
            "inputs": inputs,
            "input_digest": sha256_digest(inputs),
            "output": output,
            "output_digest": sha256_digest(output),
        }
        publications = [
            publish_report(args.output_directory, json.loads(canonical_bytes(value)))
            for value in (result, report)
        ]
        print(
            json.dumps(
                {
                    **publications[-1],
                    **output,
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                    "wrote": any(item["wrote"] for item in publications),
                },
                sort_keys=True,
            )
        )
    except (
        OSError,
        ValueError,
        ArithmeticError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(2, f"history-seed compilation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
