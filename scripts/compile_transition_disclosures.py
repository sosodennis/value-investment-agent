"""Bind existing original operating disclosures to an explicit conditional study."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from pathlib import Path

from fundamental_service.contracts import QualityStatus
from fundamental_service.facts import CanonicalMappingV1, MappingObservationScopeV1
from fundamental_service.operating_disclosures import (
    DISCLOSURE_CONCEPTS,
    ConditionalTransitionDisclosuresV1,
    conditional_transition_disclosures,
    disclosure_policy_digest,
)
from fundamental_service.operating_label_contracts import OperatingComparisonRequestV1
from fundamental_service.accounting_fields import (
    AccountingFieldRequestV1,
    extract_accounting_fields,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError

from audit_history_study_labels import decode_json
from plan_history_study_precision import ROOT, DesignError, digest, publish_report


def compile_disclosures(
    seed: OperatingComparisonRequestV1,
) -> tuple[OperatingComparisonRequestV1, dict[str, object]]:
    decision = seed.decision
    if decision.transition_disclosures is not None or any(
        fact.normalized_field == "filed_operating_evidence" for fact in decision.facts
    ):
        raise DesignError("seed must retain its original missing-disclosure state")
    newest = max(original.source.available_at for original in decision.source.originals)
    originals = tuple(
        original
        for original in decision.source.originals
        if original.source.available_at == newest
    )
    if len(originals) != 1:
        raise DesignError("latest decision original is ambiguous")
    original = originals[0]
    period = decision.periods[-1]
    mappings = []
    facts = []
    observations = []
    for concept in DISCLOSURE_CONCEPTS:
        retained = tuple(f for f in original.report.facts if f.concept == concept)
        selected = tuple(
            fact
            for fact in retained
            if fact.period_start == period.period_start
            and fact.period_end == period.period_end
            and not fact.dimensions
            and fact.consolidation_scope == "consolidated"
        )
        if len(selected) != 1:
            raise DesignError(
                "one current consolidated observation is required per disclosure"
            )
        observation = selected[0]
        scope = MappingObservationScopeV1(
            issuer_id=decision.source.identity.issuer_id,
            accession_number=original.source.accession_number,
            raw_content_hash=original.source.content_hash,
            parser_input_hash=original.source.parser_input_hash,
            parser_replay_digest=original.report.replay_digest(),
            observation_digests=(sha256_digest(observation),),
        )
        payload = {
            "contract_version": "fundamental.v1",
            "source_concept": concept,
            "normalized_field": "filed_operating_evidence",
            "mapping_version": decision.mapping_version,
            "confidence": "unresolved",
            "status": "provisional",
            "observation_scope": scope.model_dump(mode="json"),
            "evidence_refs": (sha256_digest(original), disclosure_policy_digest()),
        }
        mapping = CanonicalMappingV1.model_validate(
            {**payload, "decision_id": f"disclosure-mapping-{sha256_digest(payload)}"}
        )
        candidates = (
            extract_accounting_fields(
                AccountingFieldRequestV1(
                    original=original,
                    normalized_fields=("filed_operating_evidence",),
                    mapping_version=decision.mapping_version,
                    mappings=(mapping,),
                )
            )
            .fields[0]
            .candidates
        )
        if len(candidates) != 1:
            raise DesignError(
                "disclosure does not reproduce through the official source mapper"
            )
        fact = candidates[0].canonical_fact(quality=QualityStatus.PROVISIONAL)
        facts.append(fact)
        mappings.append(mapping)
        observations.append(
            {
                "concept": concept,
                "observation_digest": sha256_digest(observation),
                "retained_candidate_digests": sorted(
                    sha256_digest(f) for f in retained
                ),
                "mapping_digest": sha256_digest(mapping),
                "mapping_decision_id": mapping.decision_id,
                "fact_id": fact.fact_id,
                "verbatim_text_digest": digest(observation.value.encode()),
            }
        )
    all_mappings = tuple(
        sorted((*decision.mappings, *mappings), key=lambda m: m.decision_id)
    )
    proof = ConditionalTransitionDisclosuresV1(
        policy_digest=disclosure_policy_digest(),
        fact_ids=tuple(sorted(fact.fact_id for fact in facts)),
    )
    updated = decision.model_copy(
        update={
            "facts": tuple(
                sorted((*decision.facts, *facts), key=lambda fact: fact.fact_id)
            ),
            "mappings": all_mappings,
            "mapping_manifest_digest": sha256_digest(all_mappings),
            "transition_disclosures": proof,
        }
    )
    conditional_transition_disclosures(
        proof,
        facts=updated.facts,
        mappings=updated.mappings,
        source=updated.source,
        period_start=period.period_start,
        period_end=period.period_end,
    )
    result = OperatingComparisonRequestV1.model_validate_json(
        canonical_bytes(
            seed.model_copy(
                update={
                    "decision": updated,
                    "decision_input_digest": sha256_digest(updated),
                }
            )
        )
    )
    audit = {
        "schema_version": "conditional-transition-disclosure-audit.v1",
        "seed_digest": sha256_digest(seed),
        "compiled_request_digest": sha256_digest(result),
        "original_digest": sha256_digest(original),
        "source": original.source.model_dump(mode="json"),
        "parser_replay_digest": original.report.replay_digest(),
        "policy": proof.model_dump(mode="json"),
        "observations": observations,
        "previous_numeric_fact_digests": sorted(
            sha256_digest(f) for f in decision.facts
        ),
        "unchanged_label_digest": sha256_digest(seed.label),
        "mapping_review_approved": False,
        "model_suitability_established": False,
        "trusted_release_published": False,
        "complete_exact_study_cases": 0,
        "supported_history_threshold": None,
    }
    return result, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
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
        raw = args.seed.read_bytes()
        seed = OperatingComparisonRequestV1.model_validate_json(
            canonical_bytes(decode_json(raw))
        )
        compiled, audit = compile_disclosures(seed)
        inputs = {
            "exact_commit": head,
            "seed_bytes_digest": digest(raw),
            "seed_digest": sha256_digest(seed),
            "tool_digest": digest(Path(__file__).read_bytes()),
            "lock_digest": digest((ROOT / "fundamental-service/uv.lock").read_bytes()),
            "runtime": {
                "python": platform.python_version(),
                "machine": platform.machine(),
                "system": platform.system(),
            },
        }
        report = {
            "inputs": inputs,
            "input_digest": sha256_digest(inputs),
            "output": audit,
            "output_digest": sha256_digest(audit),
        }
        request_publication = publish_report(
            args.output_directory, json.loads(canonical_bytes(compiled))
        )
        audit_publication = publish_report(args.output_directory, report)
        print(
            json.dumps(
                {
                    "request": request_publication,
                    "audit": audit_publication,
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                },
                sort_keys=True,
            )
        )
    except (
        OSError,
        ValueError,
        KeyError,
        SnapshotError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(2, f"conditional transition compilation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
