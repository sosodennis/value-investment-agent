"""Capture immutable SEC inputs and prepare issuer-period mapping review evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from .history_mapping_audit import (
    DEFAULT_COHORT_MANIFEST,
    ROOT,
    MappingAuditError,
    _array,
    _decision_targets,
    _filings,
    _load_snapshot_for,
    _object,
    _read_json,
    _selected_issuers,
    _text,
)
from .history_replay import (
    _ensure_tracked_tree_clean,
    _resolve_commit,
    _runtime_pins,
    _write_content_addressed,
)
from .policies import initial_model_specs, initial_policy_records
from .sec_source import SecEdgarSourceAdapter, SecRequestPolicy, SecSourceError
from .serialization import canonical_bytes, sha256_digest
from .valuation_requirements import valuation_requirements_profile

DEFAULT_DIRECTORY = ROOT / "docs/acceptance/issue-361-full-model-inputs-v1"
SOURCE_PROFILE = "sec-companyfacts-full-model-review-v1"
MAPPING_VERSION = "sec-fcff-issuer-period-candidates-v1"

# These are review candidates, never aliases or approved canonical mappings.
CONCEPT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "cost_of_revenue": ("CostOfGoodsAndServicesSold", "CostOfRevenue"),
    "operating_income": ("OperatingIncomeLoss",),
    "income_before_tax": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ),
    "income_tax_expense": ("IncomeTaxExpenseBenefit",),
    "net_income": ("NetIncomeLoss",),
    "depreciation_and_amortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
    ),
    "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "operating_lease_cost": ("OperatingLeaseCost",),
    "finance_lease_cost": (),
    "stock_based_compensation": ("ShareBasedCompensation",),
    "basic_weighted_average_shares": ("WeightedAverageNumberOfSharesOutstandingBasic",),
    "diluted_weighted_average_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ),
    "operating_current_receivables": ("AccountsReceivableNetCurrent",),
    "inventory": ("InventoryNet",),
    "contract_assets": ("ContractWithCustomerAssetCurrent",),
    "operating_current_payables": ("AccountsPayableCurrent",),
    "accrued_operating_liabilities": ("AccruedLiabilitiesCurrent",),
    "deferred_revenue": (
        "ContractWithCustomerLiabilityCurrent",
        "DeferredRevenueCurrent",
    ),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    "current_interest_bearing_debt": ("LongTermDebtCurrent", "ShortTermBorrowings"),
    "long_term_interest_bearing_debt": ("LongTermDebtNoncurrent",),
    "current_operating_lease_liabilities": ("OperatingLeaseLiabilityCurrent",),
    "long_term_operating_lease_liabilities": ("OperatingLeaseLiabilityNoncurrent",),
    "current_finance_lease_liabilities": ("FinanceLeaseLiabilityCurrent",),
    "long_term_finance_lease_liabilities": ("FinanceLeaseLiabilityNoncurrent",),
    "preferred_claims": ("PreferredStockValue",),
    "noncontrolling_interests": ("MinorityInterest",),
    "common_shares_outstanding": (
        "CommonStockSharesOutstanding",
        "dei:EntityCommonStockSharesOutstanding",
    ),
    "convertible_instruments": (),
    "dilutive_instruments": (),
    "other_share_classes": (),
    "filed_operating_evidence": (),
}


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_immutable(path: Path, payload: bytes) -> bool:
    if path.exists():
        if path.read_bytes() != payload:
            raise MappingAuditError(f"immutable input differs: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".sec-input-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def _source_key(cik: str, accession: str, decision_at: str) -> str:
    return sha256_digest(
        {
            "cik": cik,
            "accession": accession,
            "valuation_timestamp": decision_at,
            "source_profile": SOURCE_PROFILE,
        }
    )


def capture_sources(
    *,
    output_directory: Path = DEFAULT_DIRECTORY,
    cohort_manifest_path: Path = DEFAULT_COHORT_MANIFEST,
    adapter: SecEdgarSourceAdapter | None = None,
) -> dict[str, object]:
    """Capture each fixed source identity once, including retrieval failures."""

    cohort = _read_json(cohort_manifest_path, "cohort manifest")
    cohort_digest = _digest(cohort_manifest_path.read_bytes())
    cohort_root = cohort_manifest_path.resolve().parents[3]
    records: list[dict[str, object]] = []
    writes = 0
    downloads = 0
    for issuer in _selected_issuers(cohort, root=cohort_root):
        cik = _text(issuer.get("cik"), "CIK")
        snapshot = _load_snapshot_for(cohort_root, issuer)
        decision, _, _, _ = _decision_targets(
            _filings(snapshot, _text(issuer.get("issuer_id"), "issuer_id")),
            _text(issuer.get("decision_accession"), "decision_accession"),
        )
        decision_at = decision.accepted_at.isoformat().replace("+00:00", "Z")
        key = _source_key(cik, decision.accession, decision_at)
        index_path = output_directory / "source_index" / f"{key}.bundle.gz"
        if index_path.exists():
            bundle = gzip.decompress(index_path.read_bytes())
            header, separator, _ = bundle.partition(b"\n")
            if not separator:
                raise MappingAuditError("source bundle receipt is missing")
            record = _object(json.loads(header), "source index")
            record = {**record, "bundle_digest": _digest(bundle)}
            if (
                record.get("source_key") != key
                or record.get("cohort_digest") != cohort_digest
                or record.get("cik") != cik
                or record.get("decision_accession") != decision.accession
                or record.get("decision_at") != decision_at
                or record.get("source_profile") != SOURCE_PROFILE
                or record.get("bundle_format") != "sec-response-receipt-v1"
            ):
                raise MappingAuditError("source index identity mismatch")
            if record.get("status") == "captured":
                _read_source(output_directory, record)
            elif record.get("status") != "capture_failed":
                raise MappingAuditError("unknown source capture status")
        else:
            record = {
                "bundle_format": "sec-response-receipt-v1",
                "source_key": key,
                "cohort_digest": cohort_digest,
                "source_profile": SOURCE_PROFILE,
                "cik": cik,
                "decision_accession": decision.accession,
                "decision_at": decision_at,
            }
            response = b""
            try:
                if adapter is None:
                    adapter = SecEdgarSourceAdapter(
                        SecRequestPolicy(
                            user_agent=os.environ.get("FUNDAMENTAL_SEC_USER_AGENT", ""),
                            min_interval_seconds=0.2,
                            timeout_seconds=45.0,
                            max_response_bytes=64_000_000,
                        )
                    )
                downloads += 1
                source = adapter.capture_company_facts(cik)
                raw = _object(json.loads(source.content), "Company Facts")
                if str(raw.get("cik")).zfill(10) != cik:
                    raise MappingAuditError(
                        "Company Facts issuer differs from source key"
                    )
                if source.captured_at is None:
                    raise MappingAuditError("SEC response has no capture timestamp")
                response = source.content
                record.update(
                    status="captured",
                    source_uri=source.uri,
                    response_sha256=_digest(source.content),
                    response_bytes=len(source.content),
                    captured_at=source.captured_at.isoformat().replace("+00:00", "Z"),
                    failure_code=None,
                )
            except SecSourceError as error:
                record.update(status="capture_failed", failure_code=error.code)
            except (json.JSONDecodeError, MappingAuditError):
                response = b""
                record.update(
                    status="capture_failed", failure_code="SEC_RESPONSE_INVALID"
                )
            bundle = canonical_bytes(record) + b"\n" + response
            writes += _write_immutable(
                index_path,
                gzip.compress(bundle, compresslevel=9, mtime=0),
            )
            record = {**record, "bundle_digest": _digest(bundle)}
        records.append(record)
    manifest: dict[str, object] = {
        "source_profile": SOURCE_PROFILE,
        "cohort_digest": cohort_digest,
        "issuer_records": records,
    }
    result = _write_content_addressed(output_directory, "source_manifest", manifest)
    return {
        "manifest": result,
        "selected_issuers": len(records),
        "captured_issuers": sum(row["status"] == "captured" for row in records),
        "downloads": downloads,
        "wrote": bool(writes or result["wrote"]),
    }


def _read_source(root: Path, record: dict[str, object]) -> dict[str, object]:
    digest = _text(record.get("response_sha256"), "response_sha256")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise MappingAuditError("invalid SEC response digest")
    key = _text(record.get("source_key"), "source key")
    if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
        raise MappingAuditError("invalid SEC source key")
    bundle = gzip.decompress((root / "source_index" / f"{key}.bundle.gz").read_bytes())
    if _digest(bundle) != record.get("bundle_digest"):
        raise MappingAuditError("SEC source bundle digest mismatch")
    header, separator, content = bundle.partition(b"\n")
    if not separator:
        raise MappingAuditError("SEC response receipt is missing")
    if _object(json.loads(header), "source receipt") != {
        key: value for key, value in record.items() if key != "bundle_digest"
    }:
        raise MappingAuditError("SEC source receipt differs from manifest")
    if _digest(content) != digest:
        raise MappingAuditError("SEC response digest mismatch")
    if len(content) != record.get("response_bytes"):
        raise MappingAuditError("SEC response byte count mismatch")
    raw = _object(json.loads(content, parse_float=Decimal), "Company Facts")
    if str(raw.get("cik")).zfill(10) != record.get("cik"):
        raise MappingAuditError("stored SEC response issuer mismatch")
    return raw


def _field_candidates(
    raw: dict[str, object],
    *,
    field: str,
    cik: str,
    accession: str,
    period_end: date,
    source_hash: str,
    available_at: str,
    duration: bool,
    amendment: bool,
    point_in_time: bool = False,
) -> list[dict[str, object]]:
    facts = _object(raw.get("facts"), "facts")
    candidates: dict[str, dict[str, object]] = {}
    for candidate in CONCEPT_CANDIDATES[field]:
        namespace, concept = (
            candidate.split(":", 1) if ":" in candidate else ("us-gaap", candidate)
        )
        concepts = _object(facts.get(namespace, {}), namespace)
        if concept not in concepts:
            continue
        definition = _object(concepts[concept], "concept definition")
        for unit, entries in _object(definition.get("units"), "concept units").items():
            for item in _array(entries, "concept facts"):
                fact = _object(item, "fact")
                if fact.get("accn") != accession or (
                    not point_in_time and fact.get("end") != period_end.isoformat()
                ):
                    continue
                expected_form = "10-K/A" if amendment else "10-K"
                reasons: list[str] = []
                if point_in_time:
                    try:
                        instant = date.fromisoformat(_text(fact.get("end"), "instant"))
                    except ValueError:
                        reasons.append("INVALID_INSTANT")
                    else:
                        if instant > date.fromisoformat(available_at[:10]):
                            reasons.append("FUTURE_INSTANT")
                if fact.get("form") != expected_form:
                    reasons.append("FORM_MISMATCH")
                expected_unit = "shares" if "shares" in field else "USD"
                if unit != expected_unit:
                    reasons.append("UNIT_MISMATCH")
                start = fact.get("start")
                if duration:
                    if not isinstance(start, str):
                        reasons.append("DURATION_MISSING")
                    else:
                        try:
                            days = (period_end - date.fromisoformat(start)).days
                        except ValueError:
                            reasons.append("INVALID_PERIOD_START")
                        else:
                            if not 350 <= days <= 380:
                                reasons.append("NON_ANNUAL_DURATION")
                elif start is not None:
                    reasons.append("INSTANT_REQUIRED")
                value = fact.get("val")
                if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                    reasons.append("NON_NUMERIC_VALUE")
                record: dict[str, object] = {
                    "cik": cik,
                    "accession": accession,
                    "available_at": available_at,
                    "concept": f"{namespace}:{concept}",
                    "field": field,
                    "period_start": start,
                    "period_end": fact.get("end"),
                    "unit": unit,
                    "value": str(value),
                    "scope": "sec_companyfacts_entity_wide_no_custom_or_dimensions",
                    "amendment": amendment,
                    "source_response_hash": source_hash,
                    "mapping_version": MAPPING_VERSION,
                    "source_fact_id": None,
                    "source_context_id": None,
                    "raw_fact": fact,
                    "rejection_reasons": sorted(reasons),
                }
                fact_id = sha256_digest(record)
                candidates[fact_id] = {"candidate_fact_id": fact_id, **record}
    return [candidates[key] for key in sorted(candidates)]


def build_review_package(
    *,
    source_manifest_path: Path,
    cohort_manifest_path: Path = DEFAULT_COHORT_MANIFEST,
) -> dict[str, object]:
    """Inventory model roles without inventing zeros, mappings, or source fact IDs."""

    manifest = _object(
        json.loads(gzip.decompress(source_manifest_path.read_bytes())),
        "source manifest",
    )
    if sha256_digest(manifest) != source_manifest_path.name.removesuffix(".json.gz"):
        raise MappingAuditError("source manifest digest mismatch")
    if manifest.get("cohort_digest") != _digest(cohort_manifest_path.read_bytes()):
        raise MappingAuditError("source manifest differs from fixed cohort")
    if manifest.get("source_profile") != SOURCE_PROFILE:
        raise MappingAuditError("source profile mismatch")
    cohort = _read_json(cohort_manifest_path, "cohort manifest")
    issuers = _selected_issuers(cohort, root=cohort_manifest_path.resolve().parents[3])
    records = [
        _object(item, "source record")
        for item in _array(manifest.get("issuer_records"), "issuer_records")
    ]
    by_cik = {_text(row.get("cik"), "CIK"): row for row in records}
    if len(by_cik) != len(records) or set(by_cik) != {row["cik"] for row in issuers}:
        raise MappingAuditError("source records changed the fixed issuer denominator")
    profile = valuation_requirements_profile("fcff_dcf")
    field_specs = {
        **{field: True for field in profile.annual_duration_fields},
        **{field: False for field in profile.annual_instant_fields},
        **{field: False for field in profile.point_in_time_fact_fields},
        "filed_operating_evidence": False,
    }
    candidate_issuers: dict[str, dict[str, set[str]]] = {
        field: {"history": set(), "label": set()} for field in field_specs
    }
    output: list[dict[str, object]] = []
    for issuer in issuers:
        cik = _text(issuer.get("cik"), "CIK")
        record = by_cik[cik]
        snapshot = _load_snapshot_for(cohort_manifest_path.resolve().parents[3], issuer)
        filings = _filings(snapshot, _text(issuer.get("issuer_id"), "issuer_id"))
        decision, history, following, _ = _decision_targets(
            filings, _text(issuer.get("decision_accession"), "decision_accession")
        )
        decision_at = decision.accepted_at.isoformat().replace("+00:00", "Z")
        if record.get("source_key") != _source_key(
            cik, decision.accession, decision_at
        ):
            raise MappingAuditError("source record decision identity mismatch")
        raw = (
            _read_source(source_manifest_path.parents[1], record)
            if record["status"] == "captured"
            else None
        )
        targets = sorted(
            (
                item
                for item in filings
                if (
                    item.accepted_at <= decision.accepted_at
                    and item.period_end in history
                )
                or (following is not None and item.accession == following.accession)
            ),
            key=lambda item: (item.accepted_at, item.accession),
        )
        rows: list[dict[str, object]] = []
        for filing in targets:
            role = (
                "label"
                if following is not None and filing.accession == following.accession
                else "history"
            )
            for field, duration in sorted(field_specs.items()):
                candidates = (
                    _field_candidates(
                        raw,
                        field=field,
                        cik=cik,
                        accession=filing.accession,
                        period_end=filing.period_end,
                        source_hash=_text(record.get("response_sha256"), "source hash"),
                        available_at=filing.accepted_at.isoformat().replace(
                            "+00:00", "Z"
                        ),
                        duration=duration,
                        amendment=filing.form == "10-K/A",
                        point_in_time=field in profile.point_in_time_fact_fields,
                    )
                    if raw is not None
                    else []
                )
                eligible = [
                    item for item in candidates if not item["rejection_reasons"]
                ]
                if eligible:
                    candidate_issuers[field][role].add(cik)
                values = {
                    (str(item["period_start"]), str(item["value"])) for item in eligible
                }
                rows.append(
                    {
                        "role": role,
                        "accession": filing.accession,
                        "period_end": filing.period_end.isoformat(),
                        "available_at": filing.accepted_at,
                        "amendment": filing.form == "10-K/A",
                        "field": field,
                        "candidate_facts": candidates,
                        "value_conflict": len(values) > 1,
                        "mapping_status": "review_required"
                        if eligible
                        else "no_eligible_candidate",
                        "missing_reason": (
                            "SOURCE_CAPTURE_FAILED"
                            if raw is None
                            else "CONCEPT_MAPPING_REQUIRES_REVIEW"
                            if not CONCEPT_CANDIDATES[field]
                            else "NO_ELIGIBLE_FACT_IN_COMPANYFACTS_PROFILE"
                            if not eligible
                            else None
                        ),
                    }
                )
        output.append(
            {
                "cik": cik,
                "decision_accession": decision.accession,
                "decision_at": decision_at,
                "source_record": record,
                "first_subsequent_original_accession": following.accession
                if following
                else None,
                "label_status": "review_required"
                if following
                else "no_subsequent_original_filing",
                "field_rows": rows,
            }
        )
    return {
        "schema_version": "sec-full-model-mapping-review-package-v1",
        "runtime": _runtime_pins(_resolve_commit()),
        "source_manifest_digest": sha256_digest(manifest),
        "cohort_digest": manifest["cohort_digest"],
        "mapping_version": MAPPING_VERSION,
        "candidate_rules_digest": sha256_digest(CONCEPT_CANDIDATES),
        "requirements_profiles": {
            model: valuation_requirements_profile(model).model_dump(mode="json")
            for model in ("fcff_dcf", "transition_fcff_dcf")
        },
        "source_selection_policy": "original annual accession and exact accepted_at; history available by decision; annual roles at report period end; point-in-time roles no later than filing availability; label from first subsequent original annual accession only; no later restatements",
        "model_versions": {
            model.model_id: model.model_version for model in initial_model_specs()
        },
        "policy_evidence": {
            policy.model_id: policy.model_dump(mode="json")
            for policy in initial_policy_records()
        },
        "independent_mapping_review": "required_not_supplied",
        "source_fact_id_status": "Company Facts omits original XBRL fact/context IDs; candidate IDs are content digests only",
        "approved_mapping_count": 0,
        "models": {
            model: {
                "selected_issuer_count": len(output),
                "reviewed_issuer_count": 0,
                "reviewed_label_count": 0,
                "fields": {
                    field: {
                        "issuers_with_history_candidate": len(
                            candidate_issuers[field]["history"]
                        ),
                        "issuers_with_label_candidate": len(
                            candidate_issuers[field]["label"]
                        ),
                    }
                    for field in valuation_requirements_profile(
                        model
                    ).required_fact_fields
                },
            }
            for model in ("fcff_dcf", "transition_fcff_dcf")
        },
        "supported_history_threshold": None,
        "issuer_rows": sorted(
            output, key=lambda row: (str(row["decision_at"]), str(row["cik"]))
        ),
    }


def write_review_package(
    package: dict[str, object], output_directory: Path
) -> dict[str, object]:
    """Write per-issuer evidence and an immutable manifest of canonical digests."""

    issuer_artifacts = []
    issuer_refs = []
    for item in _array(package.get("issuer_rows"), "review issuers"):
        issuer = _object(item, "review issuer")
        artifact = _write_content_addressed(output_directory, "mapping_issuers", issuer)
        issuer_artifacts.append(artifact)
        issuer_refs.append({"cik": issuer["cik"], "sha256": artifact["sha256"]})
    manifest = {key: value for key, value in package.items() if key != "issuer_rows"}
    manifest["issuer_refs"] = issuer_refs
    manifest["full_package_digest"] = sha256_digest(package)
    artifact = _write_content_addressed(output_directory, "mapping_review", manifest)
    return {
        "input_digest": package["source_manifest_digest"],
        "output_digest": artifact["sha256"],
        "manifest": artifact,
        "issuer_artifacts": issuer_artifacts,
        "wrote": artifact["wrote"] or any(item["wrote"] for item in issuer_artifacts),
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "review-package"))
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--source-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        _ensure_tracked_tree_clean(str(Path(__file__).resolve().relative_to(ROOT)))
        if args.command == "capture":
            result = capture_sources(output_directory=args.output_directory)
        else:
            if args.source_manifest is None:
                parser.error("review-package requires --source-manifest")
            result = write_review_package(
                build_review_package(source_manifest_path=args.source_manifest),
                args.output_directory,
            )
        print(
            json.dumps(
                {"commit_sha": _resolve_commit(), "command_result": "exit 0", **result},
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, MappingAuditError, SecSourceError) as error:
        print(f"history replay inputs failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
