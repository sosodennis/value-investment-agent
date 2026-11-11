"""Capture and measure point-in-time SEC revenue concept candidates."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

from .history_cohort import load_frame, select_sample
from .history_sufficiency_report import (
    Filing,
    first_subsequent_original_filing,
)
from .sec_source import SecEdgarSourceAdapter, SecRequestPolicy, SecSourceError
from .snapshots import CapturedSource, SnapshotError

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COHORT_MANIFEST = (
    ROOT / "docs/acceptance/issue-359-sec-cohort-v1/capture_manifest.json"
)
DEFAULT_OUTPUT_DIRECTORY = ROOT / "docs/acceptance/issue-361-sec-mapping-v1"
_ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
_TOTAL_REVENUE_TAG_CANDIDATES = frozenset(
    {
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    }
)
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}")
_ANNUAL_DURATION_DAYS = (350, 380)

JsonObject = dict[str, object]


class MappingAuditError(ValueError):
    """Raised when cohort or SEC mapping evidence is inconsistent."""


class RevenueFact(TypedDict):
    accession_number: str
    form: str
    unit: str
    period_start: str | None
    period_end: str
    value: str
    fiscal_period: str | None
    fiscal_year: int | str | None
    filed: str | None
    frame: str | None


class RevenueConcept(TypedDict):
    concept: str
    label: str | None
    facts: list[RevenueFact]


class ConceptSummary(TypedDict):
    label: str | None
    issuer_clusters_with_candidate_facts: int
    issuer_clusters_with_three_of_five_candidate: int
    issuer_clusters_with_matching_first_subsequent_fact: int
    issuer_clusters_with_history_and_label: int


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_fiscal_year(value: object) -> int | str | None:
    return value if isinstance(value, (str, int)) else None


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise MappingAuditError(f"{label} must be an integer")
    return value


def _revenue_fact(value: object) -> RevenueFact:
    raw = _object(value, "revenue fact")
    return RevenueFact(
        accession_number=_text(raw.get("accession_number"), "fact accession"),
        form=_text(raw.get("form"), "fact form"),
        unit=_text(raw.get("unit"), "fact unit"),
        period_start=_optional_text(raw.get("period_start")),
        period_end=_text(raw.get("period_end"), "fact period end"),
        value=_text(raw.get("value"), "fact value"),
        fiscal_period=_optional_text(raw.get("fiscal_period")),
        fiscal_year=_optional_fiscal_year(raw.get("fiscal_year")),
        filed=_optional_text(raw.get("filed")),
        frame=_optional_text(raw.get("frame")),
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _object(value: object, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise MappingAuditError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise MappingAuditError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MappingAuditError(f"{label} must be non-empty text")
    return value


def _timestamp(value: object, label: str) -> datetime:
    raw = _text(value, label)
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        result = datetime.fromisoformat(raw)
    except ValueError as error:
        raise MappingAuditError(f"{label} must be an ISO timestamp") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise MappingAuditError(f"{label} must include a timezone")
    return result.astimezone(UTC)


def _date(value: object, label: str) -> date:
    try:
        return date.fromisoformat(_text(value, label))
    except ValueError as error:
        raise MappingAuditError(f"{label} must be an ISO date") from error


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path, label: str) -> JsonObject:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, json.JSONDecodeError) as error:
        raise MappingAuditError(f"cannot read {label}: {error}") from error


def _read_cohort_snapshot(cohort_root: Path, issuer: JsonObject) -> JsonObject:
    relative = _text(issuer.get("snapshot_path"), "snapshot_path")
    path = (cohort_root / relative).resolve()
    if cohort_root.resolve() not in path.parents or not path.is_file():
        raise MappingAuditError(f"cohort snapshot is missing: {relative}")
    packed = path.read_bytes()
    if _sha256(packed) != issuer.get("snapshot_sha256"):
        raise MappingAuditError(f"cohort snapshot hash mismatch: {relative}")
    try:
        content = gzip.decompress(packed)
        snapshot = _object(json.loads(content), "cohort issuer snapshot")
    except (OSError, EOFError, json.JSONDecodeError) as error:
        raise MappingAuditError(f"cohort snapshot is invalid: {relative}") from error
    if len(packed) != issuer.get("snapshot_bytes"):
        raise MappingAuditError(f"cohort snapshot size mismatch: {relative}")
    if snapshot.get("cik") != issuer.get("cik") or snapshot.get(
        "decision_accession"
    ) != issuer.get("decision_accession"):
        raise MappingAuditError(f"cohort snapshot identity mismatch: {relative}")
    return snapshot


def _filings(snapshot: JsonObject, issuer_id: str) -> tuple[Filing, ...]:
    filings: list[Filing] = []
    for index, value in enumerate(_array(snapshot.get("filings"), "filings")):
        row = _object(value, f"filings[{index}]")
        form = _text(row.get("form"), "filing form")
        accession = _text(row.get("accession_number"), "filing accession")
        if form not in _ANNUAL_FORMS or not _ACCESSION.fullmatch(accession):
            continue
        filings.append(
            Filing(
                issuer_id=issuer_id,
                accession=accession,
                form=form,
                period_end=_date(row.get("report_period_end"), "report_period_end"),
                accepted_at=_timestamp(row.get("accepted_at"), "accepted_at"),
            )
        )
    return tuple(filings)


def _decision_targets(
    filings: tuple[Filing, ...], decision_accession: str
) -> tuple[Filing, tuple[date, ...], Filing | None, dict[str, str]]:
    decisions = [item for item in filings if item.accession == decision_accession]
    if len(decisions) != 1 or decisions[0].form != "10-K":
        raise MappingAuditError("decision accession must identify one original 10-K")
    decision = decisions[0]
    history_periods = tuple(
        sorted(
            {
                item.period_end
                for item in filings
                if item.form == "10-K"
                and item.accepted_at <= decision.accepted_at
                and item.period_end <= decision.period_end
            }
        )[-5:]
    )
    following = first_subsequent_original_filing(decision, filings)
    allowed: dict[str, str] = {}
    for item in filings:
        is_history_fact = (
            item.period_end in history_periods
            and item.accepted_at <= decision.accepted_at
        )
        is_subsequent_label = (
            following is not None
            and item.accession == following.accession
            and item.form == "10-K"
        )
        if is_history_fact or is_subsequent_label:
            allowed[item.accession] = item.form
    return decision, history_periods, following, allowed


def _extract_revenue_concepts(
    raw: JsonObject,
    *,
    cik: str,
    allowed_accessions: dict[str, str],
    target_periods: frozenset[date],
) -> tuple[RevenueConcept, ...]:
    raw_cik = raw.get("cik")
    if not str(raw_cik or "").isdigit() or str(raw_cik).zfill(10) != cik.zfill(10):
        raise MappingAuditError("SEC Company Facts CIK differs from the cohort issuer")
    facts_root = _object(raw.get("facts"), "Company Facts facts")
    us_gaap = _object(facts_root.get("us-gaap"), "Company Facts us-gaap")
    concepts: list[RevenueConcept] = []
    for concept_name, raw_concept in sorted(us_gaap.items()):
        if concept_name not in _TOTAL_REVENUE_TAG_CANDIDATES:
            continue
        concept = _object(raw_concept, f"us-gaap.{concept_name}")
        label_value = concept.get("label")
        label = label_value if isinstance(label_value, str) else None
        units = _object(concept.get("units"), f"{concept_name}.units")
        candidate_facts: list[RevenueFact] = []
        for unit, raw_records in sorted(units.items()):
            for index, raw_record in enumerate(
                _array(raw_records, f"{concept_name}.{unit}")
            ):
                record = _object(raw_record, f"{concept_name}.{unit}[{index}]")
                accession_value = record.get("accn")
                if not isinstance(accession_value, str):
                    continue
                accession = accession_value
                if (
                    accession not in allowed_accessions
                    or record.get("form") != allowed_accessions[accession]
                ):
                    continue
                if record.get("form") not in _ANNUAL_FORMS:
                    continue
                try:
                    period_end = _date(record.get("end"), "fact end")
                except MappingAuditError:
                    continue
                if period_end not in target_periods:
                    continue
                raw_start = record.get("start")
                period_start: str | None = None
                if isinstance(raw_start, str):
                    try:
                        start = _date(raw_start, "fact start")
                    except MappingAuditError:
                        continue
                    period_start = start.isoformat()
                value = record.get("val")
                if not isinstance(value, (str, int, float, Decimal)) or isinstance(
                    value, bool
                ):
                    continue
                candidate_facts.append(
                    RevenueFact(
                        accession_number=accession,
                        form=str(record["form"]),
                        unit=str(unit),
                        period_start=period_start,
                        period_end=period_end.isoformat(),
                        value=str(value),
                        fiscal_period=_optional_text(record.get("fp")),
                        fiscal_year=_optional_fiscal_year(record.get("fy")),
                        filed=_optional_text(record.get("filed")),
                        frame=_optional_text(record.get("frame")),
                    )
                )
        if candidate_facts:
            candidate_facts.sort(
                key=lambda item: (
                    item["period_end"],
                    item["period_start"] or "",
                    item["unit"],
                    item["accession_number"],
                    item["value"],
                )
            )
            concepts.append(
                RevenueConcept(
                    concept=concept_name,
                    label=label,
                    facts=candidate_facts,
                )
            )
    return tuple(concepts)


def _issuer_capture(
    source: CapturedSource,
    *,
    selected: JsonObject,
    snapshot: JsonObject,
    cohort_manifest_sha256: str,
) -> JsonObject:
    cik = _text(selected.get("cik"), "selected CIK")
    issuer_id = _text(selected.get("issuer_id"), "selected issuer_id")
    decision_accession = _text(selected.get("decision_accession"), "decision_accession")
    filings = _filings(snapshot, issuer_id)
    decision, history_periods, following, allowed = _decision_targets(
        filings, decision_accession
    )
    target_periods = set(history_periods)
    if following is not None:
        target_periods.add(following.period_end)
    raw = _object(
        json.loads(source.content, parse_float=Decimal), "SEC Company Facts response"
    )
    concepts = _extract_revenue_concepts(
        raw,
        cik=cik,
        allowed_accessions=allowed,
        target_periods=frozenset(target_periods),
    )
    if source.captured_at is None:
        raise MappingAuditError("SEC source capture timestamp is missing")
    return {
        "schema_version": "issue-361-sec-revenue-candidate-v1",
        "issuer_id": issuer_id,
        "cik": cik,
        "decision_accession": decision_accession,
        "cohort_manifest_sha256": cohort_manifest_sha256,
        "decision_available_at": decision.accepted_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "history_window_period_ends": [item.isoformat() for item in history_periods],
        "first_subsequent_original_accession": following.accession
        if following
        else None,
        "first_subsequent_period_end": following.period_end.isoformat()
        if following
        else None,
        "source_uri": source.uri,
        "source_response_sha256": _sha256(source.content),
        "source_response_bytes": len(source.content),
        "captured_at": source.captured_at.isoformat().replace("+00:00", "Z"),
        "source_scope": "us-gaap_companyfacts_entity_wide_no_custom_facts_or_dimensions",
        "concepts": list(concepts),
    }


def _selected_issuers(
    cohort_manifest: JsonObject, *, root: Path = ROOT
) -> tuple[JsonObject, ...]:
    frame = load_frame(
        root / "docs/acceptance/issue-359-cohort-protocol-v1.json",
        root / "docs/acceptance/issue-359-sec-cohort-v1/frame_manifest.json",
        root=root,
    )
    selected = select_sample(frame)["selected"]
    selected_by_cik = {item["cik"]: item for item in selected}
    manifest_issuers = _array(cohort_manifest.get("issuers"), "cohort issuers")
    rows = tuple(_object(item, "cohort issuer") for item in manifest_issuers)
    if {row.get("cik") for row in rows} != set(selected_by_cik):
        raise MappingAuditError(
            "cohort manifest differs from the preselected issuer set"
        )
    normalized: list[JsonObject] = []
    for row in rows:
        cik = _text(row.get("cik"), "cohort CIK")
        selected_row = selected_by_cik[cik]
        if row.get("decision_accession") != selected_row["decision_accession"]:
            raise MappingAuditError("cohort decision accession differs from protocol")
        normalized.append({**selected_row, **row})
    return tuple(sorted(normalized, key=lambda row: str(row["cik"])))


def _load_snapshot_for(cohort_root: Path, row: JsonObject) -> JsonObject:
    snapshot = _read_cohort_snapshot(cohort_root, row)
    if snapshot.get("issuer_id") != row.get("issuer_id"):
        raise MappingAuditError("cohort snapshot issuer differs from manifest")
    return snapshot


def capture_mapping_evidence(
    *,
    cohort_manifest_path: Path = DEFAULT_COHORT_MANIFEST,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    adapter: SecEdgarSourceAdapter | None = None,
) -> JsonObject:
    cohort_manifest_path = cohort_manifest_path.resolve()
    cohort_root = cohort_manifest_path.parent.parent.parent.parent
    cohort_manifest = _read_json(cohort_manifest_path, "cohort manifest")
    cohort_hash = _sha256(cohort_manifest_path.read_bytes())
    selected = _selected_issuers(cohort_manifest, root=cohort_root)
    if adapter is None:
        user_agent = os.environ.get("FUNDAMENTAL_SEC_USER_AGENT", "")
        adapter = SecEdgarSourceAdapter(
            SecRequestPolicy(
                user_agent=user_agent,
                min_interval_seconds=0.2,
                timeout_seconds=45.0,
                max_response_bytes=64_000_000,
            )
        )
    output_directory = output_directory.resolve()
    manifest_path = output_directory / "manifest.json"
    existing = (
        _read_json(manifest_path, "mapping evidence manifest")
        if manifest_path.exists()
        else None
    )
    if existing is not None and (
        existing.get("cohort_manifest_sha256") != cohort_hash
        or existing.get("cohort_id") != cohort_manifest.get("cohort_id")
    ):
        raise MappingAuditError("existing evidence manifest belongs to another cohort")
    prior_rows = (
        {
            _text(row.get("cik"), "evidence CIK"): row
            for row in (
                _object(item, "evidence issuer")
                for item in _array(existing.get("issuers"), "evidence issuers")
            )
        }
        if existing is not None
        else {}
    )
    evidence_rows: list[JsonObject] = []
    failures = 0
    for issuer in selected:
        cik = _text(issuer.get("cik"), "selected CIK")
        snapshot = _load_snapshot_for(cohort_root, issuer)
        relative_path = f"data/{cik}.json.gz"
        evidence_path = output_directory / relative_path
        prior = prior_rows.get(cik, {})
        if evidence_path.exists():
            packed = evidence_path.read_bytes()
            try:
                evidence = _object(
                    json.loads(gzip.decompress(packed)), "stored mapping evidence"
                )
            except (OSError, EOFError, json.JSONDecodeError) as error:
                raise MappingAuditError(
                    f"stored mapping evidence is invalid: {cik}"
                ) from error
            if (
                evidence.get("cik") != cik
                or evidence.get("decision_accession")
                != issuer.get("decision_accession")
                or evidence.get("cohort_manifest_sha256") != cohort_hash
            ):
                raise MappingAuditError(
                    f"stored mapping evidence identity mismatch: {cik}"
                )
            row: JsonObject = {
                **issuer,
                "capture_status": "captured",
                "evidence_path": relative_path,
                "evidence_sha256": _sha256(packed),
                "source_response_sha256": evidence.get("source_response_sha256"),
                "source_response_bytes": evidence.get("source_response_bytes"),
                "captured_at": evidence.get("captured_at"),
                "failure_code": None,
            }
            if prior.get("capture_status") == "captured" and (
                prior.get("evidence_sha256") != row["evidence_sha256"]
            ):
                raise MappingAuditError(f"stored mapping evidence hash mismatch: {cik}")
        else:
            try:
                source = adapter.capture_company_facts(cik)
                evidence = _issuer_capture(
                    source,
                    selected=issuer,
                    snapshot=snapshot,
                    cohort_manifest_sha256=cohort_hash,
                )
                packed = gzip.compress(_canonical_json(evidence), mtime=0)
                _write_atomic(evidence_path, packed)
                row = {
                    **issuer,
                    "capture_status": "captured",
                    "evidence_path": relative_path,
                    "evidence_sha256": _sha256(packed),
                    "source_response_sha256": evidence["source_response_sha256"],
                    "source_response_bytes": evidence["source_response_bytes"],
                    "captured_at": evidence["captured_at"],
                    "failure_code": None,
                }
            except SecSourceError as error:
                failures += 1
                row = {
                    **issuer,
                    "capture_status": "retrieval_failed",
                    "evidence_path": relative_path,
                    "evidence_sha256": None,
                    "source_response_sha256": None,
                    "source_response_bytes": None,
                    "captured_at": None,
                    "failure_code": error.code,
                }
        evidence_rows.append(row)
        manifest = {
            "schema_version": "issue-361-sec-mapping-manifest-v1",
            "cohort_id": cohort_manifest.get("cohort_id"),
            "cohort_manifest_path": str(cohort_manifest_path.relative_to(ROOT)),
            "cohort_manifest_sha256": cohort_hash,
            "selected_issuer_clusters": len(selected),
            "request_interval_seconds": 0.2,
            "status": "partial" if failures else "in_progress",
            "issuers": [*evidence_rows],
        }
        _write_atomic(manifest_path, _canonical_json(manifest))
    complete = all(row["capture_status"] == "captured" for row in evidence_rows)
    manifest["status"] = "complete" if complete else "partial"
    _write_atomic(manifest_path, _canonical_json(manifest))
    return manifest


def _annual_usd_fact(
    concept: RevenueConcept,
    *,
    period_end: date,
    filings_by_accession: dict[str, Filing],
    as_of: datetime,
    accession: str | None = None,
) -> tuple[RevenueFact | None, bool]:
    candidates: list[tuple[datetime, RevenueFact]] = []
    for fact in concept["facts"]:
        if fact["unit"] != "USD" or fact["period_start"] is None:
            continue
        if _date(fact["period_end"], "candidate period_end") != period_end:
            continue
        if accession is not None and fact["accession_number"] != accession:
            continue
        filing = filings_by_accession.get(fact["accession_number"])
        if filing is None or filing.form not in _ANNUAL_FORMS:
            continue
        if accession is None and filing.accepted_at > as_of:
            continue
        start = _date(fact["period_start"], "candidate period_start")
        if (
            not _ANNUAL_DURATION_DAYS[0]
            <= (period_end - start).days
            <= _ANNUAL_DURATION_DAYS[1]
        ):
            continue
        candidates.append((filing.accepted_at, fact))
    if not candidates:
        return None, False
    latest_at = max(available_at for available_at, _ in candidates)
    latest = [fact for available_at, fact in candidates if available_at == latest_at]
    distinct = {(fact["period_start"], fact["value"]) for fact in latest}
    if len(distinct) > 1:
        return None, True
    return min(latest, key=lambda fact: fact["accession_number"]), False


def _fact_id(concept: str, fact: RevenueFact) -> str:
    value = "|".join(
        (
            concept,
            fact["accession_number"],
            fact["unit"],
            fact["period_start"] or "instant",
            fact["period_end"],
            fact["value"],
        )
    )
    return f"sec-revenue-{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def _issuer_report(
    issuer: JsonObject,
    snapshot: JsonObject,
    evidence: JsonObject | None,
) -> JsonObject:
    issuer_id = _text(issuer.get("issuer_id"), "issuer_id")
    decision_accession = _text(issuer.get("decision_accession"), "decision_accession")
    filings = _filings(snapshot, issuer_id)
    decision, history_periods, following, _allowed = _decision_targets(
        filings, decision_accession
    )
    concepts: list[RevenueConcept] = []
    if evidence is not None:
        for raw_concept in _array(evidence.get("concepts"), "evidence concepts"):
            item = _object(raw_concept, "revenue concept")
            concept_name = _text(item.get("concept"), "concept")
            if concept_name not in _TOTAL_REVENUE_TAG_CANDIDATES:
                continue
            concepts.append(
                RevenueConcept(
                    concept=concept_name,
                    label=_optional_text(item.get("label")),
                    facts=[
                        _revenue_fact(fact)
                        for fact in _array(item.get("facts"), "concept facts")
                    ],
                )
            )
    filings_by_accession = {item.accession: item for item in filings}
    rows: list[JsonObject] = []
    for concept in concepts:
        selected_facts: list[JsonObject] = []
        conflicts: list[str] = []
        for period_end in history_periods:
            fact, conflict = _annual_usd_fact(
                concept,
                period_end=period_end,
                filings_by_accession=filings_by_accession,
                as_of=decision.accepted_at,
            )
            if conflict:
                conflicts.append(period_end.isoformat())
            selected_facts.append(
                {
                    "period_end": period_end.isoformat(),
                    "fact_id": _fact_id(concept["concept"], fact) if fact else None,
                    "source_accession": fact["accession_number"] if fact else None,
                    "value": fact["value"] if fact else None,
                }
            )
        history_count = sum(item["fact_id"] is not None for item in selected_facts)
        label_fact = None
        label_conflict = False
        if following is not None:
            label_fact, label_conflict = _annual_usd_fact(
                concept,
                period_end=following.period_end,
                filings_by_accession=filings_by_accession,
                as_of=following.accepted_at,
                accession=following.accession,
            )
        rows.append(
            {
                "concept": concept["concept"],
                "label": concept["label"],
                "mapping_status": "unreviewed_candidate",
                "history_fact_count": history_count,
                "history_three_of_five_candidate": len(history_periods) == 5
                and history_count >= 3,
                "history_conflict_period_ends": conflicts,
                "history_period_facts": selected_facts,
                "first_subsequent_fact_id": _fact_id(concept["concept"], label_fact)
                if label_fact
                else None,
                "first_subsequent_conflict": label_conflict,
                "first_subsequent_accession": following.accession
                if following
                else None,
            }
        )
    rows.sort(key=lambda row: str(row["concept"]))
    period_comparisons: list[JsonObject] = []
    for period_end in history_periods:
        observed: list[JsonObject] = []
        for concept in concepts:
            fact, conflict = _annual_usd_fact(
                concept,
                period_end=period_end,
                filings_by_accession=filings_by_accession,
                as_of=decision.accepted_at,
            )
            if fact is not None or conflict:
                observed.append(
                    {
                        "concept": concept["concept"],
                        "source_accession": fact["accession_number"] if fact else None,
                        "value": fact["value"] if fact else None,
                        "conflict": conflict,
                    }
                )
        values = {item["value"] for item in observed if item["value"] is not None}
        period_comparisons.append(
            {
                "period_end": period_end.isoformat(),
                "candidate_facts": observed,
                "candidate_values_differ": len(values) > 1,
                "interpretation": "concept values require scope review; equality is not proof of semantic equivalence",
            }
        )
    return {
        "issuer_id": issuer_id,
        "cik": issuer.get("cik"),
        "decision_accession": decision_accession,
        "decision_available_at": decision.accepted_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "history_window_period_ends": [item.isoformat() for item in history_periods],
        "first_subsequent_original_accession": following.accession
        if following
        else None,
        "evidence_status": "captured" if evidence is not None else "missing",
        "source_response_sha256": evidence.get("source_response_sha256")
        if evidence
        else None,
        "period_candidate_comparisons": period_comparisons,
        "candidate_concepts": rows,
    }


def build_mapping_report(
    *,
    cohort_manifest_path: Path = DEFAULT_COHORT_MANIFEST,
    evidence_manifest_path: Path = DEFAULT_OUTPUT_DIRECTORY / "manifest.json",
) -> JsonObject:
    cohort_manifest_path = cohort_manifest_path.resolve()
    evidence_manifest_path = evidence_manifest_path.resolve()
    cohort_root = cohort_manifest_path.parent.parent.parent.parent
    cohort_manifest = _read_json(cohort_manifest_path, "cohort manifest")
    evidence_manifest = _read_json(evidence_manifest_path, "mapping evidence manifest")
    cohort_hash = _sha256(cohort_manifest_path.read_bytes())
    if evidence_manifest.get(
        "cohort_manifest_sha256"
    ) != cohort_hash or evidence_manifest.get("cohort_id") != cohort_manifest.get(
        "cohort_id"
    ):
        raise MappingAuditError("mapping evidence is not bound to this cohort manifest")
    issuers = _selected_issuers(cohort_manifest, root=cohort_root)
    evidence_rows = {
        _text(row.get("cik"), "evidence CIK"): row
        for row in (
            _object(item, "evidence issuer")
            for item in _array(evidence_manifest.get("issuers"), "evidence issuers")
        )
    }
    if set(evidence_rows) != {str(row["cik"]) for row in issuers}:
        raise MappingAuditError("mapping evidence changed the preselected issuer set")
    output_rows: list[JsonObject] = []
    concept_counts: dict[str, ConceptSummary] = defaultdict(
        lambda: {
            "label": None,
            "issuer_clusters_with_candidate_facts": 0,
            "issuer_clusters_with_three_of_five_candidate": 0,
            "issuer_clusters_with_matching_first_subsequent_fact": 0,
            "issuer_clusters_with_history_and_label": 0,
        }
    )
    captured_count = 0
    for issuer in issuers:
        cik = str(issuer["cik"])
        snapshot = _load_snapshot_for(cohort_root, issuer)
        manifest_row = evidence_rows[cik]
        evidence: JsonObject | None = None
        if manifest_row.get("capture_status") == "captured":
            relative = _text(manifest_row.get("evidence_path"), "evidence_path")
            evidence_path = (evidence_manifest_path.parent / relative).resolve()
            if evidence_manifest_path.parent.resolve() not in evidence_path.parents:
                raise MappingAuditError("evidence path is outside its directory")
            packed = evidence_path.read_bytes()
            if _sha256(packed) != manifest_row.get("evidence_sha256"):
                raise MappingAuditError(f"mapping evidence hash mismatch: {cik}")
            try:
                evidence = _object(
                    json.loads(gzip.decompress(packed)), "issuer mapping evidence"
                )
            except (OSError, EOFError, json.JSONDecodeError) as error:
                raise MappingAuditError(
                    f"mapping evidence is invalid: {cik}"
                ) from error
            if (
                evidence.get("cik") != cik
                or evidence.get("decision_accession")
                != issuer.get("decision_accession")
                or evidence.get("cohort_manifest_sha256") != cohort_hash
            ):
                raise MappingAuditError(f"mapping evidence identity mismatch: {cik}")
            captured_count += 1
        row = _issuer_report(issuer, snapshot, evidence)
        output_rows.append(row)
        for raw_candidate in _array(
            row["candidate_concepts"], "issuer candidate concepts"
        ):
            candidate = _object(raw_candidate, "issuer candidate concept")
            concept = _text(candidate.get("concept"), "candidate concept")
            summary = concept_counts[concept]
            summary["label"] = _optional_text(candidate.get("label"))
            summary["issuer_clusters_with_candidate_facts"] += int(
                _integer(candidate["history_fact_count"], "history_fact_count") > 0
            )
            has_history = candidate["history_three_of_five_candidate"] is True
            summary["issuer_clusters_with_three_of_five_candidate"] += int(has_history)
            has_label = candidate["first_subsequent_fact_id"] is not None
            summary["issuer_clusters_with_matching_first_subsequent_fact"] += int(
                has_label
            )
            summary["issuer_clusters_with_history_and_label"] += int(
                has_history and has_label
            )

    concept_summary = [
        {"concept": concept, **values}
        for concept, values in sorted(concept_counts.items())
    ]
    candidate_screen_count = sum(
        any(
            _object(candidate, "issuer candidate concept")[
                "history_three_of_five_candidate"
            ]
            is True
            for candidate in _array(
                row["candidate_concepts"], "issuer candidate concepts"
            )
        )
        for row in output_rows
    )
    return {
        "schema_version": "issue-361-sec-revenue-mapping-report-v2",
        "cohort_id": cohort_manifest.get("cohort_id"),
        "cohort_manifest_sha256": cohort_hash,
        "evidence_manifest_sha256": _sha256(evidence_manifest_path.read_bytes()),
        "selected_issuer_clusters": len(issuers),
        "captured_issuer_clusters": captured_count,
        "candidate_mapping_status": "unreviewed_exact_total_revenue_tag_candidates",
        "candidate_selection_policy": {
            "policy_version": "us-gaap-total-revenue-tag-candidates-v1",
            "concepts": sorted(_TOTAL_REVENUE_TAG_CANDIDATES),
            "interpretation": "candidate screening only; concept tags are not approved issuer-period mappings",
        },
        "candidate_tag_screen": {
            "issuer_clusters_with_one_listed_tag_covering_three_of_five": candidate_screen_count,
            "denominator": len(issuers),
            "interpretation": "unreviewed tag screen only; this is neither canonical coverage nor an upper bound because issuer scope and unlisted/custom facts are not reviewed",
        },
        "candidate_concepts": concept_summary,
        "threshold_decision": {
            "status": "underpowered",
            "supported_history_threshold": None,
            "three_of_five_status": "unvalidated_provisional_candidate",
            "forecast_accuracy": "not_measured_no_historical_fundamental_service_forecasts",
            "mapping_review": "issuer_period_unit_scope_and_concept_review_required",
        },
        "source_scope_limitations": [
            "Company Facts includes non-custom taxonomy facts that apply to the filing entity.",
            "Company Facts does not include custom taxonomy facts or dimensional facts.",
            "A missing candidate tag does not establish that the filing has no revenue fact.",
            "Revenue-like component, proceeds, and segment tags are not treated as entity total revenue candidates.",
            "Exact candidate tags can still differ in issuer, period, and reporting scope; no mapping is approved by this screen.",
        ],
        "period_value_comparison_scope": "candidate tags can report different scopes; differing values identify a review target and do not select a canonical fact",
        "issuer_rows": output_rows,
    }


def _write_report(report: JsonObject, output_path: Path) -> bool:
    payload = _canonical_json(report)
    if output_path.exists() and output_path.read_bytes() == payload:
        return False
    _write_atomic(output_path, payload)
    return True


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument(
        "--cohort-manifest", type=Path, default=DEFAULT_COHORT_MANIFEST
    )
    capture_parser.add_argument(
        "--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY
    )
    report_parser = subparsers.add_parser("report")
    report_parser.add_argument(
        "--cohort-manifest", type=Path, default=DEFAULT_COHORT_MANIFEST
    )
    report_parser.add_argument(
        "--evidence-manifest",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY / "manifest.json",
    )
    report_parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY / "report.json"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            manifest = capture_mapping_evidence(
                cohort_manifest_path=args.cohort_manifest,
                output_directory=args.output_directory,
            )
            captured = sum(
                _object(row, "manifest issuer")["capture_status"] == "captured"
                for row in _array(manifest["issuers"], "manifest issuers")
            )
            print(
                json.dumps(
                    {
                        "manifest": str(args.output_directory / "manifest.json"),
                        "manifest_sha256": _sha256(
                            (args.output_directory / "manifest.json").read_bytes()
                        ),
                        "selected_issuer_clusters": manifest[
                            "selected_issuer_clusters"
                        ],
                        "captured_issuer_clusters": captured,
                        "status": manifest["status"],
                    },
                    sort_keys=True,
                )
            )
            return 0 if manifest["status"] == "complete" else 2
        report = build_mapping_report(
            cohort_manifest_path=args.cohort_manifest,
            evidence_manifest_path=args.evidence_manifest,
        )
        wrote = _write_report(report, args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "sha256": _sha256(args.output.read_bytes()),
                    "candidate_mapping_status": report["candidate_mapping_status"],
                    "captured_issuer_clusters": report["captured_issuer_clusters"],
                    "wrote": wrote,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        MappingAuditError,
        SnapshotError,
        SecSourceError,
        ValueError,
    ) as error:
        print(f"SEC mapping audit {args.command} failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
