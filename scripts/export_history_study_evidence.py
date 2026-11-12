"""Replay pinned Fundamental conditional evidence into the fixed research panel."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import Field

from fundamental_service.contracts import StrictModel
from fundamental_service.operating_label_contracts import OperatingComparisonRequestV1
from fundamental_service.operating_labels import replay_operating_comparison
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.serialization import canonical_bytes, sha256_digest

from analyze_history_study import (
    MANIFEST_DIGEST,
    MODELS,
    ROOT,
    TARGETS,
    WINDOWS,
    DesignError,
    decode_panel,
    digest,
    list_value,
    object_value,
    read_document,
    text_value,
)
from plan_history_study_precision import publish_report

POLICY = "formal-conditional-evidence-export-v1"


class FileReference(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceEntry(StrictModel):
    request: FileReference
    forecast: FileReference
    comparison: FileReference

    def identity(self) -> dict[str, str]:
        return {
            "request": self.request.sha256,
            "forecast": self.forecast.sha256,
            "comparison": self.comparison.sha256,
        }


class RuntimePins(StrictModel):
    python: str
    implementation: str
    machine: str
    system: str
    packages: dict[str, str]
    uv_lock_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceIndex(StrictModel):
    schema_version: Literal["history-study-evidence-index.v1"]
    fixed_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime: RuntimePins
    entries: tuple[EvidenceEntry, ...] = Field(min_length=1, max_length=300)


def runtime_pins() -> RuntimePins:
    return RuntimePins(
        python=platform.python_version(),
        implementation=platform.python_implementation(),
        machine=platform.machine(),
        system=platform.system(),
        packages={
            name: version(name)
            for name in ("pydantic", "arelle-release", "cryptography")
        },
        uv_lock_digest=digest((ROOT / "fundamental-service/uv.lock").read_bytes()),
    )


def read_evidence(reference: FileReference, directory: Path) -> bytes:
    path = directory / reference.path
    raw = path.read_bytes()
    if digest(raw) != reference.sha256:
        raise DesignError("frozen evidence content digest mismatch")
    if canonical_bytes(read_document(path)) != raw:
        raise DesignError("frozen evidence requires canonical serialization")
    return raw


def export_evidence(
    manifest: object, index: EvidenceIndex, directory: Path
) -> dict[str, object]:
    """Recompute official outputs; conditional rows never supply exact losses."""
    if (
        sha256_digest(manifest) != MANIFEST_DIGEST
        or index.fixed_manifest_digest != MANIFEST_DIGEST
    ):
        raise DesignError("fixed 100-issuer manifest digest differs")
    if index.runtime != runtime_pins():
        raise DesignError("installed runtime differs from frozen pins")
    decisions = {
        text_value(row["issuer_id"]): row
        for value in list_value(object_value(manifest)["issuer_decisions"])
        for row in (object_value(value),)
    }
    retained: dict[tuple[str, int], dict[str, object]] = {}
    summaries = []
    conditional_issuers = set()
    common_identities: dict[str, str] = {}
    requests = set()
    entries = sorted(index.entries, key=lambda entry: entry.request.sha256)
    for entry in entries:
        if entry.request.sha256 in requests:
            raise DesignError("duplicate frozen request")
        requests.add(entry.request.sha256)
        request = OperatingComparisonRequestV1.model_validate_json(
            read_evidence(entry.request, directory)
        )
        decision = request.decision
        issuer = f"CIK:{decision.source.identity.issuer_id}"
        origin = text_value(
            json.loads(canonical_bytes(decision.source.valuation_timestamp))
        )
        frozen = decisions.get(issuer)
        if frozen is None or origin != frozen["decision_at"]:
            raise DesignError("issuer replacement or decision-date substitution")
        if frozen["label_horizon_matches_forecast"] is not True or (
            frozen["label_accession"] is None
            or len(request.label.source.originals) != 1
            or request.label.source.originals[0].source.accession_number
            != frozen["label_accession"]
        ):
            raise DesignError("conditional evidence differs from frozen first original")
        if not any(
            original.source.accession_number == frozen["decision_accession"]
            and original.report_period_end == decision.periods[-1].period_end
            for original in decision.source.originals
        ):
            raise DesignError("decision accession and base period must remain frozen")
        years = len(decision.periods)
        key = issuer, years
        if key in retained:
            raise DesignError("duplicate issuer/history arm")
        forecast = replay_operating_scenarios(decision)
        comparison = replay_operating_comparison(request)
        # Preserve shared assumptions while excluding older arm-specific periods.
        common = sha256_digest(
            {
                "label": request.label,
                "inventory": request.filing_inventory,
                "inventory_evidence_digest": request.inventory_evidence_digest,
                "models": decision.model_versions,
                "model_specs": {
                    row.model_id: row.model_spec_digest for row in forecast.results
                },
                "composer_version": comparison.composer_version,
                "numerical_policy_version": comparison.numerical_policy_version,
                "label_policy_digest": comparison.label_policy_digest,
                "pairing_policy": request.pairing_policy,
                "mapping_version": decision.mapping_version,
                "mapping_manifest_digest": decision.mapping_manifest_digest,
                "source_selection": decision.source_selection_policy,
                "policy_digest": decision.policy_digest,
                "scope": decision.scope_assumption_evidence_digests,
                "protocol": (request.protocol_version, decision.protocol_version),
                "base": decision.periods[-1],
                "scenario_grid": [
                    {
                        "scenario_id": scenario.scenario_id,
                        "asset_fraction": scenario.operating_asset_fraction,
                        "liability_fraction": scenario.operating_liability_fraction,
                        "common_capex_fractions": {
                            period.fiscal_year: scenario.continuing_capex_fractions[
                                period.fiscal_year
                            ]
                            for period in decision.periods[-3:]
                        },
                    }
                    for scenario in decision.scenarios
                ],
            }
        )
        if common_identities.setdefault(issuer, common) != common:
            raise DesignError("history arms cannot change the comparison basis")
        if (
            canonical_bytes(forecast) != read_evidence(entry.forecast, directory)
            or canonical_bytes(comparison) != read_evidence(entry.comparison, directory)
            or comparison.forecast_output_digest != forecast.output_digest
        ):
            raise DesignError(
                "supplied outputs differ from official Fundamental replay"
            )
        retained[key] = {
            "issuer_id": issuer,
            "decision_at": origin,
            "years": years,
            "artifact_digests": entry.identity(),
            "comparison_basis_digest": common,
            "request": object_value(json.loads(canonical_bytes(request))),
            "forecast": object_value(json.loads(canonical_bytes(forecast))),
            "comparison": object_value(json.loads(canonical_bytes(comparison))),
        }
        for model in MODELS:
            rows = tuple(row for row in comparison.comparisons if row.model_id == model)
            scored = sum(
                row.status == "provisional_conditional_comparison" for row in rows
            )
            if scored:
                conditional_issuers.add(issuer)
            summaries.append(
                {
                    "issuer_id": issuer,
                    "years": years,
                    "model": model,
                    "retained_comparisons": len(rows),
                    "conditional_comparisons": scored,
                    "abstained_comparisons": len(rows) - scored,
                    "conditional_labels": sum(
                        label.status == "provisional_conditional_label"
                        for label in comparison.labels
                    ),
                    "abstained_labels": sum(
                        label.status == "abstained" for label in comparison.labels
                    ),
                    "issue_codes": sorted(
                        {code for row in rows for code in row.issue_codes}
                    ),
                }
            )
    cases = []
    for issuer, frozen in sorted(decisions.items()):
        observations = []
        for model in MODELS:
            for target in TARGETS:
                for years in WINDOWS:
                    evidence = retained.get((issuer, years))
                    reasons = {"EXACT_RELEASE_BOUND_LABEL_UNAVAILABLE"}
                    kind, status = "unavailable", "missing"
                    hashes: list[str] = []
                    if frozen["label_accession"] is None:
                        reasons.add("FROZEN_FIRST_ORIGINAL_LABEL_MISSING")
                    if frozen["label_horizon_matches_forecast"] is not True:
                        reasons.add("FROZEN_LABEL_HORIZON_MISMATCH")
                    if evidence is None:
                        reasons.add("HISTORY_WINDOW_EVIDENCE_MISSING")
                    else:
                        hashes = sorted(
                            set(
                                text_value(value)
                                for value in object_value(
                                    evidence["artifact_digests"]
                                ).values()
                            )
                        )
                        if target == "next_annual_undiscounted_fcff":
                            kind, status = "conditional_scenario", "abstained"
                            reasons.add("CONDITIONAL_SCENARIOS_NOT_EXACT_GROUND_TRUTH")
                            comparison_rows = object_value(evidence["comparison"])[
                                "comparisons"
                            ]
                            for value in list_value(comparison_rows):
                                row = object_value(value)
                                if row["model_id"] == model:
                                    reasons.update(
                                        text_value(code)
                                        for code in list_value(row["issue_codes"])
                                    )
                        else:
                            reasons.add("FORMAL_REVENUE_COMPARISON_UNAVAILABLE")
                    observations.append(
                        {
                            "model": model,
                            "target": target,
                            "years": years,
                            "status": status,
                            "label_kind": kind,
                            "input_policy": POLICY,
                            "comparison_key": sha256_digest(
                                {
                                    "issuer": issuer,
                                    "origin": frozen["decision_at"],
                                    "model": model,
                                    "target": target,
                                    "basis": common_identities.get(issuer),
                                    "policy": POLICY,
                                }
                            ),
                            "signed_error": None,
                            "naive_absolute_error": None,
                            "scale": None,
                            "reasons": sorted(reasons),
                            "evidence_digests": hashes,
                        }
                    )
        cases.append(
            {
                "issuer_id": issuer,
                "decision_at": frozen["decision_at"],
                "observations": observations,
            }
        )
    panel = {
        "schema_version": "history-study-loss-panel.v1",
        "analysis_scope": "exploratory_method_validation",
        "fixed_manifest_digest": MANIFEST_DIGEST,
        "cases": cases,
    }
    decode_panel(panel, manifest)
    return {
        "schema_version": "history-study-evidence-export.v1",
        "evidence_authority": "recomputed_conditional_arithmetic_not_trusted_release",
        "loss_panel": panel,
        "loss_panel_digest": sha256_digest(panel),
        "conditional_evidence": [retained[key] for key in sorted(retained)],
        "arm_summaries": sorted(
            summaries, key=lambda row: (row["issuer_id"], row["years"], row["model"])
        ),
        "represented_issuers": len({key[0] for key in retained}),
        "independent_conditional_issuers": len(conditional_issuers),
        "complete_exact_study_cases": 0,
        "uncertainty": "conditional_scenario_grid_is_not_an_issuer_sampling_distribution",
        "supported_history_threshold": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "evidence-index", "output-directory"):
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
        index = EvidenceIndex.model_validate_json(
            canonical_bytes(read_document(args.evidence_index))
        )
        output = export_evidence(
            read_document(args.manifest), index, args.evidence_index.parent
        )
        inputs = {
            "issue": 377,
            "exact_commit": head,
            "fixed_manifest_digest": MANIFEST_DIGEST,
            "evidence_index_digest": sha256_digest(
                sorted(
                    (entry.identity() for entry in index.entries),
                    key=lambda row: row["request"],
                )
            ),
            "runtime": index.runtime,
            "tool_digest": digest(Path(__file__).read_bytes()),
            "publication_tool_digest": digest(
                (ROOT / "scripts/plan_history_study_precision.py").read_bytes()
            ),
        }
        report = {
            "inputs": inputs,
            "input_digest": sha256_digest(inputs),
            "output": output,
            "output_digest": sha256_digest(output),
        }
        panel_publication = publish_report(args.output_directory, output["loss_panel"])
        publication = publish_report(
            args.output_directory, json.loads(canonical_bytes(report))
        )
        print(
            json.dumps(
                {
                    **publication,
                    "wrote": publication["wrote"] or panel_publication["wrote"],
                    "publications": {
                        "panel": panel_publication,
                        "report": publication,
                    },
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                    "loss_panel_digest": output["loss_panel_digest"],
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
        parser.exit(2, f"history-study evidence export failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
