"""Build deterministic, digest-addressed issue #361 replay preflight evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import zlib
from datetime import UTC, datetime
from importlib.metadata import version
from math import sqrt
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict

from .policies import initial_model_specs, initial_policy_records
from .serialization import canonical_bytes, sha256_digest
from .valuation_requirements import valuation_requirements_profile

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COHORT_MANIFEST = (
    ROOT / "docs/acceptance/issue-359-sec-cohort-v1/capture_manifest.json"
)
DEFAULT_EVIDENCE_MANIFEST = (
    ROOT / "docs/acceptance/issue-361-sec-mapping-v1/manifest.json"
)
DEFAULT_MAPPING_REPORT = ROOT / "docs/acceptance/issue-361-sec-mapping-v1/report.json"
DEFAULT_OUTPUT_DIRECTORY = ROOT / "docs/acceptance/issue-361-replay-preflight-v1"
PROTOCOL_VERSION = "sec-history-replay-preflight-v1"
SOURCE_PROFILE = "sec-companyfacts-revenue-candidate-v1"
MAPPING_VERSION = "us-gaap-total-revenue-tag-candidates-v1"
EXPECTED_ISSUERS = 100
WILSON_Z_95 = 1.959963984540054

JsonObject: TypeAlias = dict[str, object]
ReplayArtifacts: TypeAlias = dict[str, JsonObject]


class ReplayPreflightError(ValueError):
    """Raised when the pinned cohort or its captured evidence is inconsistent."""


class ArtifactWriteResult(TypedDict):
    path: str
    sha256: str
    wrote: bool


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _object(value: object, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ReplayPreflightError(f"{label} must be a JSON object")
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ReplayPreflightError(f"{label} has a non-string object key")
        result[key] = item
    return result


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ReplayPreflightError(f"{label} must be a JSON array")
    result: list[object] = []
    result.extend(value)
    return result


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReplayPreflightError(f"{label} must be non-empty text")
    return value


def _texts(value: object, label: str) -> list[str]:
    return [
        _text(item, f"{label}[{index}]")
        for index, item in enumerate(_array(value, label))
    ]


def _read_object(path: Path, label: str) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayPreflightError(f"cannot read {label}: {error}") from error
    return _object(value, label)


def _iso_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReplayPreflightError(f"{label} must be a timestamp")
    raw = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ReplayPreflightError(f"{label} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayPreflightError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _safe_child(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ReplayPreflightError(f"{label} must be a relative path")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise ReplayPreflightError(f"{label} is missing or escapes its root")
    return path


def _load_issuer_evidence(
    evidence_root: Path, entry: JsonObject, cohort_hash: str
) -> tuple[JsonObject | None, str | None]:
    if entry.get("capture_status") != "captured":
        return None, None
    path = _safe_child(evidence_root, entry.get("evidence_path"), "evidence_path")
    packed = path.read_bytes()
    if _sha256(packed) != entry.get("evidence_sha256"):
        raise ReplayPreflightError(f"evidence hash mismatch: {path.name}")
    try:
        evidence = json.loads(gzip.decompress(packed))
    except (OSError, EOFError, json.JSONDecodeError) as error:
        raise ReplayPreflightError(f"invalid captured evidence: {path.name}") from error
    evidence = _object(evidence, f"captured evidence {path.name}")
    if (
        evidence.get("cik") != entry.get("cik")
        or evidence.get("decision_accession") != entry.get("decision_accession")
        or evidence.get("cohort_manifest_sha256") != cohort_hash
    ):
        raise ReplayPreflightError(f"captured evidence identity mismatch: {path.name}")
    return evidence, _sha256(packed)


def _wilson_interval(successes: int, trials: int) -> dict[str, float | None]:
    if trials <= 0:
        return {"lower": None, "upper": None}
    proportion = successes / trials
    denominator = 1 + WILSON_Z_95**2 / trials
    center = (proportion + WILSON_Z_95**2 / (2 * trials)) / denominator
    radius = (
        WILSON_Z_95
        * sqrt(
            proportion * (1 - proportion) / trials + WILSON_Z_95**2 / (4 * trials**2)
        )
        / denominator
    )
    return {"lower": max(0.0, center - radius), "upper": min(1.0, center + radius)}


def _runtime_pins(commit_sha: str) -> dict[str, str]:
    lock_path = ROOT / "fundamental-service/uv.lock"
    return {
        "commit_sha": commit_sha,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "pydantic_version": version("pydantic"),
        "fundamental_service_lock_sha256": _sha256(lock_path.read_bytes()),
    }


def _resolve_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ReplayPreflightError("cannot resolve the exact replay commit")
    commit_sha = result.stdout.strip()
    if len(commit_sha) != 40 or any(c not in "0123456789abcdef" for c in commit_sha):
        raise ReplayPreflightError("Git returned an invalid full commit SHA")
    return commit_sha


def _ensure_tracked_tree_clean(
    required_source: str = "fundamental-service/src/fundamental_service/history_replay.py",
) -> None:
    tracked = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT, check=False)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=ROOT, check=False
    )
    source = subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            required_source,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if tracked.returncode != 0 or staged.returncode != 0 or source.returncode != 0:
        raise ReplayPreflightError(
            "the committed replay source and tracked inputs must be clean"
        )


def _candidate_label_rows(
    issuer_row: JsonObject, evidence: JsonObject | None, mapping_version: str
) -> tuple[list[JsonObject], int]:
    candidates: list[JsonObject] = []
    if evidence is None:
        return candidates, 0
    next_accession = issuer_row.get("first_subsequent_original_accession")
    period_end = evidence.get("first_subsequent_period_end")
    if not isinstance(next_accession, str) or not isinstance(period_end, str):
        return candidates, 0

    concepts = _array(evidence.get("concepts"), "captured evidence concepts")
    raw_count = 0
    for concept_entry in concepts:
        concept_entry = _object(concept_entry, "captured evidence concept")
        concept = concept_entry.get("concept")
        if not isinstance(concept, str):
            continue
        raw_facts = _array(concept_entry.get("facts"), f"{concept}.facts")
        for raw_fact in raw_facts:
            raw_fact = _object(raw_fact, f"{concept} fact")
            if (
                raw_fact.get("accession_number") != next_accession
                or raw_fact.get("period_end") != period_end
                or raw_fact.get("form") != "10-K"
                or raw_fact.get("unit") != "USD"
            ):
                continue
            fact = {
                "accession_number": next_accession,
                "concept": concept,
                "fact_id": "sec-companyfacts-"
                + sha256_digest(
                    {
                        "cik": issuer_row.get("cik"),
                        "accession_number": next_accession,
                        "concept": concept,
                        "period_start": raw_fact.get("period_start"),
                        "period_end": period_end,
                        "unit": raw_fact.get("unit"),
                        "value": raw_fact.get("value"),
                        "source_sha256": evidence.get("source_response_sha256"),
                        "mapping_version": mapping_version,
                    }
                ),
                "form": "10-K",
                "is_amendment": False,
                "amends_accession": None,
                "amendment_scope": None,
                "filing_version": "original",
                "mapping_status": "unreviewed_candidate",
                "mapping_version": mapping_version,
                "period_end": period_end,
                "period_start": raw_fact.get("period_start"),
                "scope": evidence.get("source_scope", "unknown"),
                "source_sha256": evidence.get("source_response_sha256"),
                "unit": raw_fact.get("unit"),
                "value": raw_fact.get("value"),
            }
            candidates.append(fact)
            raw_count += 1
    candidates.sort(
        key=lambda fact: (
            str(fact["concept"]),
            str(fact["period_start"] or ""),
            "" if fact["value"] is None else str(fact["value"]),
            str(fact["fact_id"]),
        )
    )
    return candidates, raw_count


def build_replay_preflight(
    *,
    cohort_manifest_path: Path = DEFAULT_COHORT_MANIFEST,
    evidence_manifest_path: Path = DEFAULT_EVIDENCE_MANIFEST,
    mapping_report_path: Path = DEFAULT_MAPPING_REPORT,
) -> ReplayArtifacts:
    """Bind existing evidence and summarize why canonical forecasts cannot run."""

    cohort_manifest_path = cohort_manifest_path.resolve()
    evidence_manifest_path = evidence_manifest_path.resolve()
    mapping_report_path = mapping_report_path.resolve()
    evidence_root = evidence_manifest_path.parent
    cohort = _read_object(cohort_manifest_path, "fixed SEC cohort manifest")
    evidence_manifest = _read_object(
        evidence_manifest_path, "mapping evidence manifest"
    )
    mapping_report = _read_object(mapping_report_path, "mapping audit report")
    cohort_hash = _sha256(cohort_manifest_path.read_bytes())
    evidence_manifest_hash = _sha256(evidence_manifest_path.read_bytes())
    mapping_report_hash = _sha256(mapping_report_path.read_bytes())

    if evidence_manifest.get("cohort_manifest_sha256") != cohort_hash:
        raise ReplayPreflightError("mapping evidence is not bound to the fixed cohort")
    if mapping_report.get("cohort_manifest_sha256") != cohort_hash:
        raise ReplayPreflightError("mapping report is not bound to the fixed cohort")
    if mapping_report.get("evidence_manifest_sha256") != evidence_manifest_hash:
        raise ReplayPreflightError(
            "mapping report is not bound to the evidence manifest"
        )
    if mapping_report.get("candidate_mapping_status") != (
        "unreviewed_exact_total_revenue_tag_candidates"
    ):
        raise ReplayPreflightError(
            "mapping report does not have the expected review state"
        )

    cohort_rows = _array(cohort.get("issuers"), "fixed cohort issuers")
    evidence_rows = _array(evidence_manifest.get("issuers"), "evidence issuers")
    report_rows = _array(
        mapping_report.get("issuer_rows"), "mapping report issuer_rows"
    )
    if len(cohort_rows) != EXPECTED_ISSUERS:
        raise ReplayPreflightError(
            "the fixed issue #359 cohort must contain 100 issuers"
        )

    def unique_by_cik(rows: list[object], label: str) -> dict[str, JsonObject]:
        result: dict[str, JsonObject] = {}
        for row in rows:
            row = _object(row, f"{label} row")
            cik = row.get("cik")
            if not isinstance(cik, str):
                raise ReplayPreflightError(f"{label} contains an invalid issuer row")
            if cik in result:
                raise ReplayPreflightError(f"{label} contains duplicate CIK {cik}")
            result[cik] = row
        return result

    fixed_by_cik = unique_by_cik(cohort_rows, "cohort manifest")
    evidence_by_cik = unique_by_cik(evidence_rows, "evidence manifest")
    report_by_cik = unique_by_cik(report_rows, "mapping report")
    if set(fixed_by_cik) != set(evidence_by_cik) or set(fixed_by_cik) != set(
        report_by_cik
    ):
        raise ReplayPreflightError("cohort, evidence, and report issuer sets differ")

    commit = _resolve_commit()
    runtime = _runtime_pins(commit)
    model_specs = {model.model_id: model for model in initial_model_specs()}
    policies = {policy.model_id: policy for policy in initial_policy_records()}
    model_ids: tuple[Literal["fcff_dcf", "transition_fcff_dcf"], ...] = (
        "fcff_dcf",
        "transition_fcff_dcf",
    )
    market_inputs_by_model = {}
    for model_id in model_ids:
        market_inputs = policies[model_id].market_inputs
        if market_inputs is None:
            raise ReplayPreflightError(f"{model_id} policy has no market inputs")
        market_inputs_by_model[model_id] = market_inputs
    input_issuers: list[JsonObject] = []
    label_issuers: list[JsonObject] = []
    forecast_rows: list[JsonObject] = []
    source_keys: set[str] = set()
    captured_count = 0
    next_filing_count = 0
    raw_label_issuer_count = 0
    raw_label_fact_count = 0

    for cik in sorted(fixed_by_cik):
        selected = fixed_by_cik[cik]
        evidence_entry = evidence_by_cik[cik]
        mapping_row = report_by_cik[cik]
        if (
            selected.get("decision_accession")
            != evidence_entry.get("decision_accession")
            or selected.get("decision_accession")
            != mapping_row.get("decision_accession")
            or selected.get("issuer_id") != mapping_row.get("issuer_id")
        ):
            raise ReplayPreflightError(f"issuer identity mismatch for CIK {cik}")

        evidence, packed_evidence_hash = _load_issuer_evidence(
            evidence_root, evidence_entry, cohort_hash
        )
        if evidence is not None:
            captured_count += 1
        decision_at = mapping_row.get("decision_available_at")
        decision_timestamp = _iso_datetime(decision_at, f"{cik}.decision_available_at")
        accession = _text(
            selected.get("decision_accession"), f"{cik}.decision_accession"
        )
        source_key = sha256_digest(
            {
                "cik": cik.zfill(10),
                "decision_accession": accession,
                "valuation_timestamp": decision_timestamp,
                "source_profile": SOURCE_PROFILE,
            }
        )
        if source_key in source_keys:
            raise ReplayPreflightError(f"duplicate SEC source identity for CIK {cik}")
        source_keys.add(source_key)

        candidates = _array(
            mapping_row.get("candidate_concepts"), f"{cik}.candidate_concepts"
        )
        for item in candidates:
            _object(item, f"{cik}.candidate_concepts item")
        candidate_label_facts, label_fact_count = _candidate_label_rows(
            mapping_row, evidence, MAPPING_VERSION
        )
        has_raw_label = label_fact_count > 0
        raw_label_issuer_count += int(has_raw_label)
        raw_label_fact_count += label_fact_count
        next_accession = mapping_row.get("first_subsequent_original_accession")
        next_filing_count += int(isinstance(next_accession, str))

        input_issuers.append(
            {
                "cik": cik,
                "decision_accession": accession,
                "decision_available_at": decision_timestamp,
                "evidence_capture_status": evidence_entry.get("capture_status"),
                "evidence_file_sha256": packed_evidence_hash,
                "evidence_response_sha256": evidence_entry.get(
                    "source_response_sha256"
                ),
                "source_profile": SOURCE_PROFILE,
                "source_scope": evidence.get("source_scope") if evidence else None,
                "source_key": source_key,
            }
        )
        label_issuers.append(
            {
                "cik": cik,
                "decision_accession": accession,
                "first_subsequent_original_accession": next_accession,
                "first_subsequent_period_end": (
                    evidence.get("first_subsequent_period_end") if evidence else None
                ),
                "candidate_facts": candidate_label_facts,
                "candidate_fact_count": label_fact_count,
                "eligible_model_label": False,
                "label_status": (
                    "unreviewed_candidate"
                    if has_raw_label
                    else "missing_or_no_qualifying_candidate"
                ),
                "reason": "no reviewed full-model field mapping is available",
            }
        )

        for model_id in model_ids:
            model = model_specs[model_id]
            policy = policies[model_id]
            profile = valuation_requirements_profile(model_id)
            available_market_evidence = tuple(
                item.available_at for item in market_inputs_by_model[model_id].evidence
            )
            market_policy_available = bool(available_market_evidence) and all(
                item <= decision_timestamp for item in available_market_evidence
            )
            forecast_rows.append(
                {
                    "cik": cik,
                    "decision_accession": accession,
                    "decision_available_at": decision_timestamp,
                    "model_id": model_id,
                    "model_version": model.model_version,
                    "requirements_profile_id": profile.profile_id,
                    "requirements_profile_digest": profile.digest,
                    "required_field_count": len(profile.required_fact_fields),
                    "policy_id": policy.policy_id,
                    "policy_version": policy.policy_version,
                    "market_policy_version": market_inputs_by_model[
                        model_id
                    ].policy_version,
                    "market_policy_evidence_available_at": sorted(
                        item.isoformat().replace("+00:00", "Z")
                        for item in available_market_evidence
                    ),
                    "market_policy_available_at_decision": market_policy_available,
                    "composer_invoked": False,
                    "composer_status": "not_invoked_no_reviewed_release_facts",
                    "valuation_status": "not_evaluated",
                    "recommended_disposition": "abstain",
                    "forecast": None,
                    "forecast_error": None,
                    "forecast_error_status": "not_measured_no_canonical_forecast",
                    "missing_reasons": [
                        "REVENUE_MAPPING_UNREVIEWED",
                        "FULL_MODEL_FIELD_MAPPING_UNAVAILABLE",
                        "NO_RELEASE_BOUND_CANONICAL_FACT_SET",
                        *(
                            []
                            if market_policy_available
                            else ["HISTORICAL_MARKET_POLICY_NOT_AVAILABLE_AT_DECISION"]
                        ),
                    ],
                }
            )

    input_artifact: JsonObject = {
        "schema_version": "issue-361-replay-input-v1",
        "protocol_version": PROTOCOL_VERSION,
        "runtime": runtime,
        "cohort_id": cohort.get("cohort_id"),
        "cohort_manifest_sha256": cohort_hash,
        "evidence_manifest_sha256": evidence_manifest_hash,
        "mapping_report_sha256": mapping_report_hash,
        "source_profile": SOURCE_PROFILE,
        "source_selection_policy": (
            "decision facts only from original annual filing accessions accepted by "
            "the decision timestamp; OOS labels only from the first following original 10-K"
        ),
        "mapping_version": MAPPING_VERSION,
        "model_versions": {
            model_id: model_specs[model_id].model_version for model_id in model_ids
        },
        "policy_versions": {
            model_id: policies[model_id].policy_version for model_id in model_ids
        },
        "issuers": input_issuers,
    }
    mapping_artifact: JsonObject = {
        "schema_version": "issue-361-mapping-audit-v1",
        "mapping_version": MAPPING_VERSION,
        "source_report_sha256": mapping_report_hash,
        "mapping_status": mapping_report.get("candidate_mapping_status"),
        "candidate_selection_policy": mapping_report.get("candidate_selection_policy"),
        "candidate_tag_screen": mapping_report.get("candidate_tag_screen"),
        "issuer_rows": [
            {
                "cik": row.get("cik"),
                "decision_accession": row.get("decision_accession"),
                "source_response_sha256": row.get("source_response_sha256"),
                "evidence_status": row.get("evidence_status"),
                "candidate_concepts": row.get("candidate_concepts"),
                "first_subsequent_original_accession": row.get(
                    "first_subsequent_original_accession"
                ),
            }
            for row in (report_by_cik[cik] for cik in sorted(report_by_cik))
        ],
    }
    forecast_artifact: JsonObject = {
        "schema_version": "issue-361-forecast-output-v1",
        "protocol_version": PROTOCOL_VERSION,
        "status": "underpowered_no_forecasts_produced",
        "forecast_rows": forecast_rows,
    }
    label_artifact: JsonObject = {
        "schema_version": "issue-361-label-output-v1",
        "protocol_version": PROTOCOL_VERSION,
        "status": "incomplete_unreviewed_candidate_labels",
        "eligible_model_labels": 0,
        "candidate_label_fact_count": raw_label_fact_count,
        "candidate_label_issuer_count": raw_label_issuer_count,
        "first_subsequent_original_filings": next_filing_count,
        "issuer_rows": label_issuers,
    }

    input_digest = sha256_digest(input_artifact)
    mapping_digest = sha256_digest(mapping_artifact)
    forecast_digest = sha256_digest(forecast_artifact)
    label_digest = sha256_digest(label_artifact)
    model_summaries: dict[str, JsonObject] = {}
    for model_id in model_ids:
        rows = [row for row in forecast_rows if row["model_id"] == model_id]
        eligible = sum(row["forecast"] is not None for row in rows)
        missing_reasons = [
            reason
            for row in rows
            for reason in _texts(row["missing_reasons"], "forecast missing_reasons")
        ]
        model_summaries[model_id] = {
            "forecast_error": None,
            "forecast_error_status": "not_measured_no_canonical_forecast",
            "forecast_coverage": {
                "numerator": eligible,
                "denominator": EXPECTED_ISSUERS,
                "fraction": eligible / EXPECTED_ISSUERS,
                "wilson_95": _wilson_interval(eligible, EXPECTED_ISSUERS),
            },
            "independent_issuer_count": eligible,
            "label_eligible_issuer_count": 0,
            "composer_invocations": sum(
                row["composer_invoked"] is True for row in rows
            ),
            "valuation_dispositions_measured": False,
            "recommended_disposition_counts": {
                "abstain": sum(
                    row["recommended_disposition"] == "abstain" for row in rows
                )
            },
            "missing_reason_counts": {
                reason: missing_reasons.count(reason)
                for reason in sorted(set(missing_reasons))
            },
        }
    report_artifact: JsonObject = {
        "schema_version": "issue-361-replay-report-v1",
        "protocol_version": PROTOCOL_VERSION,
        "status": "underpowered",
        "replay_status": "preflight_blocked_before_service_composer",
        "runtime": runtime,
        "cohort_id": cohort.get("cohort_id"),
        "selected_issuer_count": len(fixed_by_cik),
        "captured_issuer_count": captured_count,
        "first_subsequent_original_filing_count": next_filing_count,
        "raw_candidate_label_issuer_count": raw_label_issuer_count,
        "raw_candidate_label_fact_count": raw_label_fact_count,
        "reviewed_mapping_issuer_count": 0,
        "eligible_model_label_issuer_count": 0,
        "model_results": model_summaries,
        "supported_history_threshold": None,
        "three_of_five_status": "unvalidated_provisional_candidate",
        "quality_dispositions": {
            "measured": False,
            "verified": 0,
            "provisional": 0,
            "abstain_recommended": len(forecast_rows),
            "underpowered": 1,
            "interpretation": "preflight only; no composer valuation dispositions were produced",
        },
        "market_policy_evidence": {
            model_id: {
                "policy_id": policies[model_id].policy_id,
                "policy_version": policies[model_id].policy_version,
                "market_policy_version": market_inputs_by_model[
                    model_id
                ].policy_version,
                "earliest_available_at": min(
                    item.available_at
                    for item in market_inputs_by_model[model_id].evidence
                )
                .isoformat()
                .replace("+00:00", "Z"),
                "latest_available_at": max(
                    item.available_at
                    for item in market_inputs_by_model[model_id].evidence
                )
                .isoformat()
                .replace("+00:00", "Z"),
                "admissible_for_decision_count": sum(
                    row["market_policy_available_at_decision"] is True
                    for row in forecast_rows
                    if row["model_id"] == model_id
                ),
            }
            for model_id in model_ids
        },
        "missing_reasons": [
            "The committed capture contains revenue-keyword candidates, not the full canonical model field set.",
            "The only listed revenue concepts remain unreviewed issuer-period mappings.",
            "No release-bound canonical facts are available for the historical decisions.",
            "The active FCFF market-policy evidence is dated after the 2016 decision dates.",
            "No canonical forecast or eligible model-field first-subsequent label can be measured.",
        ],
        "artifact_digests": {
            "input": input_digest,
            "mapping": mapping_digest,
            "forecast_output": forecast_digest,
            "label_output": label_digest,
        },
        "acceptance_gates": {
            "mapping_replay": "not_passed_unreviewed_mapping",
            "history_replay": "not_run_no_release_bound_canonical_facts",
            "forecast": "not_run_no_release_bound_canonical_facts",
            "label": "candidate_only_incomplete_model_fields",
            "deterministic_rerun": "preflight_idempotency_only_full_replay_not_run",
            "service_backed": "not_run_no_valid_replay_package",
        },
    }
    return {
        "input": input_artifact,
        "mapping": mapping_artifact,
        "forecast_output": forecast_artifact,
        "label_output": label_artifact,
        "report": report_artifact,
    }


def _write_content_addressed(
    output_directory: Path, kind: str, value: JsonObject
) -> ArtifactWriteResult:
    payload = canonical_bytes(value)
    digest = _sha256(payload)
    compressed_payload = gzip.compress(payload, compresslevel=9, mtime=0)
    path = output_directory / kind / f"{digest}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing_payload = gzip.decompress(path.read_bytes())
        except (OSError, EOFError, zlib.error) as error:
            raise ReplayPreflightError(
                f"content-addressed artifact is not valid gzip at {path}"
            ) from error
        if existing_payload != payload:
            raise ReplayPreflightError(f"content-address collision at {path}")
        wrote = False
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=".replay-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(compressed_payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        wrote = True
    return {"path": str(path.resolve()), "sha256": digest, "wrote": wrote}


def write_preflight_artifacts(
    artifacts: ReplayArtifacts, output_directory: Path
) -> dict[str, ArtifactWriteResult]:
    """Write immutable content-addressed artifacts with atomic replacement."""

    return {
        name: _write_content_addressed(output_directory, name, artifacts[name])
        for name in ("input", "mapping", "forecast_output", "label_output", "report")
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-manifest", type=Path, default=DEFAULT_COHORT_MANIFEST)
    parser.add_argument(
        "--evidence-manifest", type=Path, default=DEFAULT_EVIDENCE_MANIFEST
    )
    parser.add_argument("--mapping-report", type=Path, default=DEFAULT_MAPPING_REPORT)
    parser.add_argument(
        "--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY
    )
    args = parser.parse_args(argv)
    try:
        _ensure_tracked_tree_clean()
        artifacts = build_replay_preflight(
            cohort_manifest_path=args.cohort_manifest,
            evidence_manifest_path=args.evidence_manifest,
            mapping_report_path=args.mapping_report,
        )
        results = write_preflight_artifacts(artifacts, args.output_directory)
        report = _object(artifacts["report"], "replay report")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "replay_status": report["replay_status"],
                    "input_digest": results["input"]["sha256"],
                    "output_digest": results["report"]["sha256"],
                    "artifacts": results,
                    "command_result": "exit 0",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except (OSError, ReplayPreflightError, ValueError) as error:
        print(f"history replay preflight failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
