"""Verify and publish the research-only methods freeze; never approve a threshold."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from fundamental_service.contracts import StrictModel
from fundamental_service.serialization import canonical_bytes, sha256_digest

from export_history_study_evidence import runtime_pins
from plan_history_study_precision import (
    MANIFEST_DIGEST,
    ROOT,
    DesignError,
    digest,
    publish_report,
)

DEPENDENCIES = (
    "docs/research/issue-377-methods-v4.json",
    "docs/research/issue-377-protocol-proposal-v3.json",
    "scripts/analyze_history_study.py",
    "scripts/export_history_study_evidence.py",
    "scripts/plan_history_study_precision.py",
    "scripts/replay_history_study_windows.py",
)


class AnalysisFreeze(StrictModel):
    schema_version: Literal["history-analysis-freeze.v1"]
    scope: Literal["fixed100_exploratory_operating_analysis_only"]
    review_status: Literal["author_methods_review_complete_not_independent_approval"]
    fixed_manifest_digest: Literal[
        "448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a"
    ]
    selected_issuers: Literal[100]
    retained_filing_targets: Literal[589]
    maximum_eligible_label_pairs: Literal[90]
    legacy_minimum_complete_pairs: Literal[100]
    legacy_gate_changed: Literal[False]
    prior_outcome_inspection: Literal["NEWMARKET_conditional_pilot_before_methods_v4"]
    primary_input_policy: Literal[
        "one_declared_policy_per_model_target_no_outcome_selection"
    ]
    uncertainty: Literal[
        "paired_issuer_percentile_bootstrap_approximate_not_guaranteed"
    ]
    precision_claim: Literal[
        "report_achieved_interval_half_width_no_power_or_adequacy_claim"
    ]
    missingness: Literal["retain_all100_no_MAR_no_finite_missing_loss_bound"]
    numerical_promotion_limits: Literal["v3_proposals_rejected_as_release_authority"]
    prospective_power_claim: Literal[False]
    independent_review_claim: Literal[False]
    promotion_enabled: Literal[False]
    supported_history_threshold: None
    method_dependencies: dict[str, str]
    decision_record: Literal["docs/research/issue-377-analysis-freeze.md"]

    @model_validator(mode="after")
    def complete_dependencies(self) -> AnalysisFreeze:
        if set(self.method_dependencies) != set(DEPENDENCIES) or any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in self.method_dependencies.values()
        ):
            raise ValueError("freeze requires every exact method dependency digest")
        return self


def verify_freeze(raw: bytes, *, root: Path) -> AnalysisFreeze:
    freeze = AnalysisFreeze.model_validate_json(raw)
    if canonical_bytes(freeze) + b"\n" != raw:
        raise DesignError("methods freeze must use canonical JSON plus one terminal LF")
    if freeze.fixed_manifest_digest != MANIFEST_DIGEST:
        raise DesignError("fixed cohort cannot be substituted")
    for relative, expected in freeze.method_dependencies.items():
        if digest((root / relative).read_bytes()) != expected:
            raise DesignError(f"frozen method dependency differs: {relative}")
    return freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-digest", required=True)
    parser.add_argument("--exact-commit", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if revision != args.exact_commit or subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ):
            raise DesignError("exact clean implementation commit is required")
        raw = args.freeze.read_bytes()
        if digest(raw) != args.freeze_digest:
            raise DesignError("freeze content digest differs")
        pinned = ROOT / "docs/research/issue-377-analysis-freeze-v1.json"
        if raw != pinned.read_bytes():
            raise DesignError("freeze differs from the committed reviewed contract")
        freeze = verify_freeze(raw, root=ROOT)
        inputs = {
            "exact_commit": revision,
            "freeze_digest": digest(raw),
            "runtime": runtime_pins(),
        }
        output = {
            "freeze": freeze,
            "dependency_hashes_match": True,
            "promotion_enabled": False,
            "supported_history_threshold": None,
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
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"methods freeze failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
