"""Build the reproducible offline evidence report for issue #356."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from math import sqrt
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = (
    ROOT / "fundamental-service/tests/fixtures/sec-edgar/capture_manifest.json"
)
DEFAULT_OUTPUT = ROOT / "docs/acceptance/issue-356-history-sufficiency-v1.json"
WINDOW = 5
MINIMUM_PERIODS = 3
MINIMUM_ISSUER_CLUSTERS = 100
WILSON_Z_95 = 1.959963984540054

FIELD_SPECS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "USD",
        "duration",
    ),
    "cost_of_revenue": ("CostOfGoodsAndServicesSold", "USD", "duration"),
    "operating_income": ("OperatingIncomeLoss", "USD", "duration"),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "USD",
        "duration",
    ),
    "tax_expense": ("IncomeTaxExpenseBenefit", "USD", "duration"),
    "depreciation_amortization": (
        "DepreciationDepletionAndAmortization",
        "USD",
        "duration",
    ),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "USD",
        "duration",
    ),
    "accounts_receivable": ("AccountsReceivableNetCurrent", "USD", "instant"),
    "inventory": ("InventoryNet", "USD", "instant"),
    "accounts_payable": ("AccountsPayableCurrent", "USD", "instant"),
    "contract_liabilities": ("ContractWithCustomerLiabilityCurrent", "USD", "instant"),
    "other_current_assets": ("OtherAssetsCurrent", "USD", "instant"),
    "accrued_liabilities": ("AccruedLiabilitiesCurrent", "USD", "instant"),
    "share_based_compensation": ("ShareBasedCompensation", "USD", "duration"),
    "diluted_weighted_average_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "shares",
        "duration",
    ),
}
FCFF_FIELDS = (
    "revenue",
    "operating_income",
    "pretax_income",
    "tax_expense",
    "depreciation_amortization",
    "capital_expenditures",
    "accounts_receivable",
    "inventory",
    "accounts_payable",
    "contract_liabilities",
    "other_current_assets",
    "accrued_liabilities",
)
MODEL_FIELDS = {
    "fcff_dcf": FCFF_FIELDS,
    "transition_fcff_dcf": FCFF_FIELDS
    + (
        "cost_of_revenue",
        "share_based_compensation",
        "diluted_weighted_average_shares",
    ),
}
UNMEASURED = {
    "fcff_dcf": [
        "reviewed normalized-tax policy",
        "canonical operating-working-capital mappings",
        "pinned model forecast outputs",
        "negative or near-zero denominator handling",
        "loss-making-period eligibility",
        "volatility and cyclicality classification",
        "acquisition or structural-break screening",
        "conflicting taxonomy-mapping diagnostics",
    ],
    "transition_fcff_dcf": [
        "reviewed normalized-tax policy",
        "canonical operating-working-capital mappings",
        "pinned model forecast outputs",
        "filed transition operating evidence",
        "negative or near-zero denominator handling",
        "loss-making-period eligibility",
        "volatility and cyclicality classification",
        "acquisition or structural-break screening",
        "conflicting taxonomy-mapping diagnostics",
    ],
}


class ReportError(ValueError):
    """Raised when source data cannot support a reproducible report."""


@dataclass(frozen=True, slots=True)
class Filing:
    issuer_id: str
    accession: str
    form: str
    period_end: date
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class Fact:
    field_id: str
    accession: str
    period_end: date
    available_at: datetime
    value: str
    period_start: date | None = None


def _obj(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReportError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ReportError(f"{label} must be an array")
    return value


def _str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReportError(f"{label} must be a non-empty string")
    return value


def _date(value: object, label: str) -> date:
    try:
        return date.fromisoformat(_str(value, label))
    except ValueError as exc:
        raise ReportError(f"{label} must be an ISO date") from exc


def _datetime(value: object, label: str) -> datetime:
    raw = _str(value, label)
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        result = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ReportError(f"{label} must be an ISO timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ReportError(f"{label} must include a timezone")
    return result.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        return _obj(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read {path}: {exc}") from exc


def _local_file(root: Path, relative: str) -> Path:
    resolved = (root / relative).resolve()
    if root.resolve() not in resolved.parents or not resolved.is_file():
        raise ReportError(f"source file is missing or outside its root: {relative}")
    return resolved


def _verify_manifest_files(manifest_path: Path, manifest: dict[str, object]) -> None:
    fixture_root = manifest_path.parent
    for collection in ("sources", "test_fixtures"):
        for index, raw in enumerate(_list(manifest.get(collection), collection)):
            record = _obj(raw, f"{collection}[{index}]")
            relative = _str(record.get("path"), f"{collection}[{index}].path")
            expected = _str(record.get("sha256"), f"{collection}[{index}].sha256")
            if _hash(_local_file(fixture_root, relative)) != expected:
                raise ReportError(f"source hash mismatch: {relative}")


def _issuer_id(uri: object) -> str:
    if not isinstance(uri, str):
        raise ReportError("SEC filing source is missing its URI")
    match = re.search(r"/Archives/edgar/data/(\d+)/", urlparse(uri).path)
    if match is None:
        raise ReportError(f"cannot parse issuer CIK from {uri}")
    return f"CIK:{match.group(1).zfill(10)}"


def _filing_row(source: dict[str, object]) -> dict[str, object]:
    accession = _str(source.get("accession_number"), "filing accession")
    available_at = _datetime(source.get("available_at"), "filing available_at")
    period_end = _date(source.get("report_period_end"), "filing report_period_end")
    issuer_id = _issuer_id(source.get("uri"))
    return {
        "row_id": f"{issuer_id}:{accession}",
        "issuer_id": issuer_id,
        "accession_number": accession,
        "form": _str(source.get("form"), "filing form"),
        "report_period_end": period_end.isoformat(),
        "available_at": _iso(available_at),
        "valuation_timestamp": _iso(available_at + timedelta(seconds=1)),
        "source_path": _str(source.get("path"), "filing path"),
        "source_sha256": _str(source.get("sha256"), "filing sha256"),
        "is_amendment": source.get("is_amendment") is True,
        "amendment_scope": source.get("amendment_scope"),
        "amends_accession": source.get("amends_accession"),
    }


def _fact_reference(fact: Fact) -> dict[str, str]:
    concept, unit, period_type = FIELD_SPECS[fact.field_id]
    period_start = fact.period_start.isoformat() if fact.period_start else "instant"
    return {
        "fact_id": f"{fact.accession}:{concept}:{unit}:{period_start}:{fact.period_end.isoformat()}",
        "field_id": fact.field_id,
        "concept": concept,
        "unit": unit,
        "period_type": period_type,
        "period_start": period_start,
        "period_end": fact.period_end.isoformat(),
        "source_accession": fact.accession,
        "available_at": _iso(fact.available_at),
        "value": fact.value,
    }


def _microsoft_snapshot(
    manifest_path: Path,
    manifest: dict[str, object],
) -> tuple[dict[str, object], bool]:
    fixture = next(
        _obj(item, "test fixture")
        for item in _list(manifest.get("test_fixtures"), "test_fixtures")
        if _obj(item, "test fixture").get("path")
        == "microsoft-2024-original-xbrl-test-package.zip"
    )
    evidence = next(
        _obj(item, "external public evidence")
        for item in _list(
            manifest.get("external_public_evidence"), "external_public_evidence"
        )
        if _obj(item, "external public evidence").get("accession_number")
        == "0000950170-24-087843"
    )
    relative = _str(fixture.get("path"), "Microsoft fixture path")
    fixture_path = _local_file(manifest_path.parent, relative)
    members: list[dict[str, object]] = []
    all_match = True
    with zipfile.ZipFile(fixture_path) as archive:
        for raw_member in _list(evidence.get("canonical_members"), "canonical members"):
            member = _obj(raw_member, "canonical member")
            name = _str(member.get("name"), "canonical member name")
            expected_size = int(member["bytes"])
            expected_hash = _str(member.get("sha256"), "canonical member sha256")
            actual = archive.read(name)
            actual_hash = hashlib.sha256(actual).hexdigest()
            matches = len(actual) == expected_size and actual_hash == expected_hash
            all_match = all_match and matches
            members.append(
                {
                    "name": name,
                    "bytes": len(actual),
                    "sha256": actual_hash,
                    "matches_canonical_sec_member": matches,
                }
            )
    available_at = _datetime(evidence.get("accepted_at"), "Microsoft accepted_at")
    index_size = int(evidence["filing_index_member_bytes"])
    filing_bytes = next(
        int(_obj(item, "canonical member")["bytes"])
        for item in _list(evidence.get("canonical_members"), "canonical members")
        if _obj(item, "canonical member").get("name", "").endswith(".htm")
    )
    accession = _str(evidence.get("accession_number"), "Microsoft accession")
    issuer_id = f"CIK:{_str(evidence.get('cik'), 'Microsoft CIK').zfill(10)}"
    row = {
        "row_id": f"{issuer_id}:{accession}",
        "issuer_id": issuer_id,
        "accession_number": accession,
        "form": _str(evidence.get("form"), "Microsoft form"),
        "report_period_end": _str(
            evidence.get("report_period_end"), "Microsoft report period"
        ),
        "is_amendment": False,
        "amendment_scope": None,
        "amends_accession": None,
        "available_at": _iso(available_at),
        "valuation_timestamp": _iso(available_at + timedelta(seconds=1)),
        "source_path": relative,
        "source_sha256": _str(fixture.get("sha256"), "Microsoft fixture sha256"),
        "source_members": members,
        "filing_index_url": _str(evidence.get("filing_index_url"), "filing index URL"),
        "filing_index_member_bytes": index_size,
        "primary_document_bytes": filing_bytes,
        "index_size_warning_bytes": index_size - filing_bytes,
        "sic": evidence.get("sic"),
        "cohort_status": "included_member_hashes_match"
        if all_match
        else "excluded_member_hash_mismatch",
        "oos_label_status": "no_subsequent_original_annual_filing_in_fixture",
    }
    return row, all_match


def _primary_cohort(
    manifest_path: Path, manifest: dict[str, object]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    included: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for raw in _list(manifest.get("sources"), "sources"):
        source = _obj(raw, "source")
        if source.get("role") != "filing":
            continue
        row = _filing_row(source)
        if row["form"] == "10-K" and not row["is_amendment"]:
            row["cohort_status"] = "included_original_filing_snapshot"
            row["cohort_reason"] = (
                "manifest records an original annual filing with a verified source hash"
            )
            included.append(row)
        else:
            row["cohort_status"] = "excluded"
            if row["is_amendment"] and row["amendment_scope"] in (None, "unknown"):
                row["exclusion_reason"] = "amendment_scope_unknown"
            elif row["is_amendment"]:
                row["exclusion_reason"] = "amendment_is_not_an_original_annual_snapshot"
            else:
                row["exclusion_reason"] = "filing_form_is_not_original_10-K"
            excluded.append(row)
    microsoft, valid_members = _microsoft_snapshot(manifest_path, manifest)
    if valid_members:
        microsoft["cohort_reason"] = (
            "canonical SEC archive member hashes match the captured fixture bytes"
        )
        included.append(microsoft)
    else:
        microsoft["exclusion_reason"] = "canonical_sec_member_hash_mismatch"
        excluded.append(microsoft)

    originals = [
        row
        for row in included
        if row["form"] == "10-K" and row["is_amendment"] is False
    ]
    for row in originals:
        row_period = _date(row["report_period_end"], "cohort report period")
        row_available_at = _datetime(row["available_at"], "cohort availability")
        later = [
            candidate
            for candidate in originals
            if candidate["issuer_id"] == row["issuer_id"]
            and _date(candidate["report_period_end"], "candidate report period")
            > row_period
            and _datetime(candidate["available_at"], "candidate availability")
            > row_available_at
        ]
        if later:
            next_row = min(
                later,
                key=lambda candidate: (
                    _date(candidate["report_period_end"], "candidate report period"),
                    _datetime(candidate["available_at"], "candidate availability"),
                ),
            )
            row["next_original_filing_snapshot"] = {
                "accession_number": next_row["accession_number"],
                "report_period_end": next_row["report_period_end"],
                "available_at": next_row["available_at"],
            }
            row["oos_label_status"] = (
                "next_original_snapshot_available_but_facts_not_loaded_for_primary_cohort"
            )
        else:
            row["next_original_filing_snapshot"] = None
            row["oos_label_status"] = "no_subsequent_original_annual_filing_in_fixture"
    return included, excluded


def _submissions(raw: dict[str, object], issuer_id: str) -> tuple[Filing, ...]:
    recent = _obj(
        _obj(raw.get("filings"), "submissions.filings").get("recent"), "recent filings"
    )
    forms = _list(recent.get("form"), "recent.form")
    accessions = _list(recent.get("accessionNumber"), "recent.accessionNumber")
    periods = _list(recent.get("reportDate"), "recent.reportDate")
    accepted = _list(recent.get("acceptanceDateTime"), "recent.acceptanceDateTime")
    result: list[Filing] = []
    for index, form in enumerate(forms):
        if form not in {"10-K", "10-K/A"}:
            continue
        if index >= min(len(accessions), len(periods), len(accepted)):
            continue
        try:
            result.append(
                Filing(
                    issuer_id=issuer_id,
                    accession=_str(accessions[index], "submission accession"),
                    form=str(form),
                    period_end=_date(periods[index], "submission reportDate"),
                    accepted_at=_datetime(
                        accepted[index], "submission acceptanceDateTime"
                    ),
                )
            )
        except ReportError:
            continue
    return tuple(sorted(result, key=lambda item: (item.period_end, item.accepted_at)))


def first_subsequent_original_filing(
    decision: Filing, filings: Sequence[Filing]
) -> Filing | None:
    later = [
        filing
        for filing in filings
        if filing.issuer_id == decision.issuer_id
        and filing.period_end > decision.period_end
        and filing.accepted_at > decision.accepted_at
    ]
    if not later:
        return None
    first_period = min(item.period_end for item in later)
    originals = [
        item
        for item in later
        if item.period_end == first_period and item.form == "10-K"
    ]
    return min(originals, key=lambda item: item.accepted_at) if originals else None


def _company_facts(
    raw: dict[str, object], filings: Sequence[Filing]
) -> tuple[Fact, ...]:
    us_gaap = _obj(
        _obj(raw.get("facts"), "companyfacts.facts").get("us-gaap"), "us-gaap"
    )
    by_accession = {filing.accession: filing for filing in filings}
    result: list[Fact] = []
    for field_id, (concept_name, unit, period_type) in FIELD_SPECS.items():
        concept = us_gaap.get(concept_name)
        if concept is None:
            continue
        unit_rows = _obj(
            _obj(concept, concept_name).get("units"), f"{concept_name}.units"
        ).get(unit)
        if unit_rows is None:
            continue
        for raw_fact in _list(unit_rows, f"{concept_name}.{unit}"):
            item = _obj(raw_fact, f"{concept_name} fact")
            accession = item.get("accn")
            if (
                item.get("form") != "10-K"
                or item.get("fp") != "FY"
                or accession not in by_accession
            ):
                continue
            end = _date(item.get("end"), "fact end")
            start = item.get("start")
            period_start: date | None = None
            if period_type == "duration":
                if not isinstance(start, str):
                    continue
                period_start = _date(start, "fact start")
                if not 350 <= (end - period_start).days <= 380:
                    continue
            elif start is not None:
                continue
            result.append(
                Fact(
                    field_id,
                    str(accession),
                    end,
                    by_accession[str(accession)].accepted_at,
                    str(item["val"]),
                    period_start,
                )
            )
    return tuple(result)


def _select_fact(
    facts: Sequence[Fact],
    field_id: str,
    period_end: date,
    as_of: datetime,
    accession: str | None = None,
) -> Fact | None:
    candidates = [
        fact
        for fact in facts
        if fact.field_id == field_id
        and fact.period_end == period_end
        and fact.available_at <= as_of
        and (accession is None or fact.accession == accession)
    ]
    if not candidates:
        return None
    latest_at = max(fact.available_at for fact in candidates)
    latest = [fact for fact in candidates if fact.available_at == latest_at]
    if len({fact.value for fact in latest}) != 1:
        return None
    return min(latest, key=lambda fact: fact.accession)


def _wilson(successes: int, trials: int) -> dict[str, float] | None:
    if trials == 0:
        return None
    z = WILSON_Z_95
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = z * sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return {
        "lower": round(max(0.0, center - half), 6),
        "upper": round(min(1.0, center + half), 6),
    }


def _history_period_gaps(periods: Sequence[date]) -> list[dict[str, object]]:
    gaps: list[dict[str, object]] = []
    for previous, current in pairwise(periods):
        elapsed_days = (current - previous).days
        if elapsed_days > 380:
            gaps.append(
                {
                    "previous_period_end": previous.isoformat(),
                    "next_period_end": current.isoformat(),
                    "elapsed_days": elapsed_days,
                    "missing_annual_period_likely": True,
                }
            )
    return gaps


def _pilot_model(
    model_id: str,
    fields: Sequence[str],
    filings: Sequence[Filing],
    facts: Sequence[Fact],
) -> dict[str, object]:
    decisions: list[dict[str, object]] = []
    coverage = {field: [] for field in fields}
    source_fact_catalog: dict[str, dict[str, str]] = {}
    pass_count = eligible_labels = complete_labels = 0
    original_filings = tuple(item for item in filings if item.form == "10-K")
    original_periods = sorted({item.period_end for item in original_filings})
    for filing in original_filings:
        as_of = filing.accepted_at + timedelta(seconds=1)
        window = [period for period in original_periods if period <= filing.period_end][
            -WINDOW:
        ]
        period_coverage: list[dict[str, object]] = []
        for period in window:
            present: list[str] = []
            fact_ids: list[str] = []
            for field in fields:
                fact = _select_fact(facts, field, period, as_of)
                if fact is None:
                    continue
                reference = _fact_reference(fact)
                source_fact_catalog[reference["fact_id"]] = reference
                present.append(field)
                fact_ids.append(reference["fact_id"])
            period_coverage.append(
                {
                    "period_end": period.isoformat(),
                    "present_fields": present,
                    "missing_fields": [
                        field for field in fields if field not in present
                    ],
                    "source_fact_ids": fact_ids,
                }
            )
        counts = {
            field: sum(field in row["present_fields"] for row in period_coverage)
            for field in fields
        }
        complete_periods = (
            sum(not row["missing_fields"] for row in period_coverage)
            if len(window) == WINDOW
            else 0
        )
        rule_passes = len(window) == WINDOW and complete_periods >= MINIMUM_PERIODS
        if len(window) == WINDOW:
            for field in fields:
                coverage[field].append(counts[field])
        if rule_passes:
            pass_count += 1
        next_filing = first_subsequent_original_filing(filing, filings)
        label_fields: list[str] = []
        label_fact_ids: list[str] = []
        if rule_passes and next_filing is not None:
            eligible_labels += 1
            for field in fields:
                fact = _select_fact(
                    facts,
                    field,
                    next_filing.period_end,
                    next_filing.accepted_at,
                    next_filing.accession,
                )
                if fact is not None:
                    label_fields.append(field)
                    reference = _fact_reference(fact)
                    source_fact_catalog[reference["fact_id"]] = reference
                    label_fact_ids.append(reference["fact_id"])
            complete_labels += len(label_fields) == len(fields)
        if len(window) != WINDOW:
            continue
        decisions.append(
            {
                "decision_accession": filing.accession,
                "report_period_end": filing.period_end.isoformat(),
                "available_at": _iso(filing.accepted_at),
                "valuation_timestamp": _iso(as_of),
                "history_window_period_ends": [period.isoformat() for period in window],
                "history_period_gaps": _history_period_gaps(window),
                "period_field_coverage": period_coverage,
                "field_period_counts": counts,
                "complete_history_periods": complete_periods,
                "three_of_five_proxy_rule_passes": rule_passes,
                "next_original_filing_accession": next_filing.accession
                if next_filing
                else None,
                "next_original_report_period_end": next_filing.period_end.isoformat()
                if next_filing
                else None,
                "next_original_available_at": _iso(next_filing.accepted_at)
                if next_filing
                else None,
                "next_label_fields_present": label_fields,
                "next_label_source_fact_ids": label_fact_ids,
            }
        )
    return {
        "model_id": model_id,
        "source_fact_catalog": [
            source_fact_catalog[key] for key in sorted(source_fact_catalog)
        ],
        "fields": [
            {
                "field_id": field,
                "concept": FIELD_SPECS[field][0],
                "mapping_status": "diagnostic_only",
            }
            for field in fields
        ],
        "unmeasured_model_requirements": UNMEASURED[model_id],
        "field_coverage": {
            field: {
                "windows_with_five_periods": len(counts),
                "windows_with_at_least_three_period_observations": sum(
                    count >= MINIMUM_PERIODS for count in counts
                ),
                "period_observations_per_window": counts,
            }
            for field, counts in coverage.items()
        },
        "diagnostic_decision_rows": decisions,
        "three_of_five_proxy_rule_pass_count": pass_count,
        "threshold_decision": {
            "status": "underpowered",
            "supported_history_threshold": None,
            "candidate_rule": f"at least {MINIMUM_PERIODS} complete periods in the latest {WINDOW} original annual filing periods",
            "reasons": [
                "single-issuer diagnostic cannot establish representative coverage or issuer-cluster precision",
                *(
                    [
                        "no next-period fact labels are available after the candidate rule"
                    ]
                    if eligible_labels == 0
                    else []
                ),
                "forecast error is not measured because historical service forecasts do not exist",
            ],
            "affected_results": "provisional_or_abstained",
        },
        "oos_label_completeness": {
            "target": "next_original_annual_filing_contains_all_measured_tag_proxies",
            "split_policy": "walk_forward_each_decision_labels_only_from_its_first_subsequent_original_10-K",
            "eligible_decisions_after_proxy_rule": eligible_labels,
            "complete_labels": complete_labels,
            "period_level_wilson_95": _wilson(complete_labels, eligible_labels),
            "period_interval_use": "descriptive_only_periods_are_clustered_by_one_issuer",
            "issuer_cluster_interval_95": None,
            "forecast_accuracy": "not_measured_no_historical_service_forecasts_exist",
        },
    }


def _merge_fact_catalog(pilot: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    catalog: dict[str, dict[str, object]] = {}
    for model_id, model_report in pilot.items():
        references = _list(
            model_report.pop("source_fact_catalog", []),
            f"{model_id}.source_fact_catalog",
        )
        for index, raw in enumerate(references):
            reference = _obj(raw, f"{model_id}.source_fact_catalog[{index}]")
            fact_id = _str(reference.get("fact_id"), "source fact ID")
            catalog[fact_id] = reference
    return [catalog[key] for key in sorted(catalog)]


def build_history_sufficiency_report(
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, object]:
    manifest_path = manifest_path.resolve()
    manifest = _read_json(manifest_path)
    _verify_manifest_files(manifest_path, manifest)
    included, excluded = _primary_cohort(manifest_path, manifest)
    sources = [
        _obj(item, "source") for item in _list(manifest.get("sources"), "sources")
    ]
    company_facts_meta = next(
        item for item in sources if item.get("role") == "company_facts"
    )
    submissions_meta = next(
        item for item in sources if item.get("path") == "apple-submissions.json"
    )
    fixture_root = manifest_path.parent
    company_facts = _read_json(
        fixture_root / _str(company_facts_meta.get("path"), "Company Facts path")
    )
    submissions = _read_json(
        fixture_root / _str(submissions_meta.get("path"), "submissions path")
    )
    uri = _str(company_facts_meta.get("uri"), "Company Facts URI")
    cik = re.search(r"/CIK(\d+)\.json$", urlparse(uri).path)
    if cik is None:
        raise ReportError("cannot resolve Apple CIK from Company Facts URI")
    issuer_id = f"CIK:{cik.group(1).zfill(10)}"
    filings = _submissions(submissions, issuer_id)
    facts = _company_facts(company_facts, filings)
    pilot = {
        model: _pilot_model(model, fields, filings, facts)
        for model, fields in MODEL_FIELDS.items()
    }
    source_fact_catalog = _merge_fact_catalog(pilot)
    return {
        "schema_version": "issue-356-history-sufficiency-v1",
        "cohort_id": "issue-356-sec-history-fixture-cohort-v1",
        "capture_manifest": {
            "path": str(manifest_path.relative_to(ROOT)),
            "sha256": _hash(manifest_path),
            "capture_version": manifest.get("capture_version"),
            "captured_at": manifest.get("captured_at"),
        },
        "candidate_history_rule": {
            "minimum_complete_periods": MINIMUM_PERIODS,
            "window_periods": WINDOW,
            "status": "candidate_not_validated",
        },
        "primary_cohort": {
            "sampling_frame": "checked_in_fixture_inventory_not_a_representative_sampling_frame",
            "issuer_identity_policy": "CIK and accession derived from captured SEC source metadata; tickers are not used",
            "issuer_identity_history_status": "not_measured_no_historical_identifier_or_successor_crosswalk_snapshots",
            "included_input_snapshots": included,
            "excluded_issuer_periods": excluded,
            "issuer_cluster_count": len({row["issuer_id"] for row in included}),
            "industry_coverage": {
                "known_sic_issuer_count": len(
                    {row["issuer_id"] for row in included if row.get("sic")}
                ),
                "known_sic_values": sorted(
                    {str(row["sic"]) for row in included if row.get("sic")}
                ),
                "unclassified_issuer_ids": sorted(
                    {row["issuer_id"] for row in included if not row.get("sic")}
                ),
                "limitation": "only SIC captured with the Microsoft filing evidence is available; later issuer metadata is not used",
            },
            "available_next_original_snapshot_pair_count": sum(
                row["next_original_filing_snapshot"] is not None for row in included
            ),
            "eligible_oos_fact_label_count": 0,
            "oos_label_limit": "primary filing snapshots do not include a complete next-filing fact panel",
        },
        "diagnostic_pilot": {
            "issuer_id": issuer_id,
            "issuer_cluster_count": 1,
            "source_class": "post_capture_sec_companyfacts_aggregate",
            "source_snapshot": {
                "path": company_facts_meta["path"],
                "sha256": company_facts_meta["sha256"],
                "available_at": company_facts_meta["available_at"],
            },
            "filing_calendar_snapshot": {
                "path": submissions_meta["path"],
                "sha256": submissions_meta["sha256"],
            },
            "fact_rows_after_annual_period_filter": len(facts),
            "point_in_time_policy": "select only original 10-K facts with acceptance time <= valuation timestamp",
            "source_fact_catalog": source_fact_catalog,
            "models": pilot,
            "use_limit": "one-issuer diagnostic only; not a representative cohort or raw filing substitute",
        },
        "sample_size_policy": {
            "binary_interval": "95_percent_wilson",
            "target_absolute_margin": 0.10,
            "minimum_independent_issuer_clusters": MINIMUM_ISSUER_CLUSTERS,
            "rationale": "100 independent clusters keep the worst-case 95% Wilson half-width below 0.10; periods within one issuer do not increase n",
            "industry_claims": "apply the same precision target within each reported industry stratum",
            "forecast_error": "not estimable until service forecasts exist and a pilot variance supports a predeclared cluster interval target",
        },
        "threshold_decision": {
            "status": "underpowered",
            "supported_history_threshold": None,
            "affected_results": "provisional_or_abstained",
            "reasons": [
                "the checked-in fixture inventory has three issuer clusters and is not a representative sampling frame",
                "industry classification is available for one issuer and historical identifier changes are unmeasured",
                "the one-issuer Company Facts diagnostic has no eligible next-period labels after the candidate rule",
                "canonical field mappings and operating-working-capital comparability are not measured",
                "no historical service forecasts exist for forecast-error evaluation",
            ],
        },
        "source_exclusions": [
            "analyst targets, consensus, Search, and LLM evidence are not read",
            "engineering golden-cohort cases do not count as issuer-period observations",
            "amendments with unknown scope are not used as first-subsequent labels",
        ],
    }


def _write_idempotently(path: Path, report: dict[str, object]) -> bool:
    data = (
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return False
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        report = build_history_sufficiency_report(args.manifest)
        wrote = _write_idempotently(args.output, report)
    except (OSError, ReportError, zipfile.BadZipFile) as exc:
        print(f"history sufficiency report failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": _hash(args.output),
                "threshold_status": report["threshold_decision"]["status"],
                "wrote": wrote,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
