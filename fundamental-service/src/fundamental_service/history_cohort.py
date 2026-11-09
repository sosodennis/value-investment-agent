"""Capture and report a reproducible, point-in-time SEC issuer cohort."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import TypedDict

from .history_sufficiency_report import (
    FIELD_SPECS,
    MODEL_FIELDS,
    MINIMUM_PERIODS,
    WINDOW,
    Fact,
    Filing,
    ReportError,
    _company_facts,
    _fact_reference,
    _history_period_gaps,
    _iso,
    _obj,
    _select_fact,
    _list,
    _str,
    _wilson,
    first_subsequent_original_filing,
)
from .sec_source import SecEdgarSourceAdapter, SecRequestPolicy, SecSourceError
from .snapshots import CapturedSource

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROTOCOL = ROOT / "docs/acceptance/issue-359-cohort-protocol-v1.json"
DEFAULT_FRAME_MANIFEST = (
    ROOT / "docs/acceptance/issue-359-sec-cohort-v1/frame_manifest.json"
)
DEFAULT_CAPTURE_MANIFEST = (
    ROOT / "docs/acceptance/issue-359-sec-cohort-v1/capture_manifest.json"
)
DEFAULT_REPORT = ROOT / "docs/acceptance/issue-359-sec-cohort-v1/report.json"
SNAPSHOT_DIRECTORY = DEFAULT_CAPTURE_MANIFEST.parent / "snapshots"
_ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
_FACT_ROW_KEYS = (
    "accn",
    "end",
    "filed",
    "form",
    "fp",
    "frame",
    "fy",
    "start",
    "val",
)
_FRAME_COLUMNS = (
    "adsh",
    "cik",
    "name",
    "sic",
    "countryinc",
    "form",
    "filed",
    "period",
    "accepted",
)

JsonObject = dict[str, object]


class FrameIssuer(TypedDict):
    issuer_id: str
    cik: str
    decision_accession: str
    decision_filed: str
    report_period_end: str
    frame_accepted: str
    countryinc: str
    sic: str | None
    stratum: str


class FrameExclusion(TypedDict):
    issuer_id: str
    decision_accession: str | None
    countryinc: str | None
    reason: str


class FrameSnapshot(TypedDict):
    protocol_scope: str
    sample_size: int
    sample_seed: str
    protocol_sha256: str
    frame_manifest_sha256: str
    frame_counts: dict[str, int]
    eligible: tuple[FrameIssuer, ...]
    excluded: tuple[FrameExclusion, ...]


class SampledIssuer(FrameIssuer):
    sample_rank: int
    selection_digest: str


class SampleSelection(TypedDict):
    selected: tuple[SampledIssuer, ...]
    population_by_stratum: dict[str, int]
    sample_by_stratum: dict[str, int]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"cannot read JSON artifact {path}: {error}") from error
    return _obj(value, f"JSON artifact {path}")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ReportError(f"{label} must be text")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReportError(f"{label} must be an integer")
    return value


def _repo_path(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ReportError(f"{label} path must be a non-empty string")
    resolved = (root / relative).resolve()
    if root.resolve() not in resolved.parents or not resolved.is_file():
        raise ReportError(f"{label} is missing or outside the repository: {relative}")
    return resolved


def _verified_snapshot(root: Path, record: JsonObject, label: str) -> bytes:
    stored = _obj(record.get("stored_snapshot"), f"{label}.stored_snapshot")
    path = _repo_path(root, stored.get("path"), label)
    packed = path.read_bytes()
    if _sha256(packed) != stored.get("stored_sha256"):
        raise ReportError(f"stored snapshot hash mismatch: {path}")
    try:
        raw = gzip.decompress(packed)
    except (OSError, EOFError) as error:
        raise ReportError(f"invalid gzip snapshot: {path}") from error
    if len(raw) != stored.get("uncompressed_bytes"):
        raise ReportError(f"snapshot size mismatch: {path}")
    if _sha256(raw) != stored.get("uncompressed_sha256"):
        raise ReportError(f"uncompressed snapshot hash mismatch: {path}")
    return raw


def _cik(value: object) -> str:
    text = str(value).strip()
    if not text.isdigit() or len(text) > 10:
        raise ReportError("SEC CIK must be numeric and at most ten digits")
    return text.zfill(10)


def _sic_stratum(value: object, definitions: JsonObject) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        return "unclassified"
    sic = int(text)
    for name, range_value in definitions.items():
        if name == "unclassified" or not isinstance(range_value, str):
            continue
        match = re.fullmatch(r"(\d{4})-(\d{4})", range_value)
        if match and int(match.group(1)) <= sic <= int(match.group(2)):
            return name
    return "unclassified"


def load_frame(
    protocol_path: Path = DEFAULT_PROTOCOL,
    frame_manifest_path: Path = DEFAULT_FRAME_MANIFEST,
    *,
    root: Path = ROOT,
) -> FrameSnapshot:
    """Verify pinned SEC frame files and return the eligible issuer population."""
    protocol_path = protocol_path.resolve()
    frame_manifest_path = frame_manifest_path.resolve()
    protocol = _read_json(protocol_path)
    manifest = _read_json(frame_manifest_path)
    if protocol.get("schema_version") != "issue-359-cohort-protocol-v1":
        raise ReportError("unsupported issue-359 sampling protocol")
    if manifest.get("schema_version") != "issue-359-sec-frame-snapshot-v1":
        raise ReportError("unsupported issue-359 frame manifest")
    sources: dict[str, JsonObject] = {}
    for source_index, source_value in enumerate(
        _list(manifest.get("sources"), "frame sources")
    ):
        source = _obj(source_value, f"frame source {source_index}")
        source_id = _str(source.get("source_id"), "frame source_id")
        sources[source_id] = source
    index_source = sources.get("sec-2016q1-master-index")
    dataset_source = sources.get("sec-2016q1-submissions")
    if not isinstance(index_source, dict) or not isinstance(dataset_source, dict):
        raise ReportError("SEC frame sources are incomplete")
    frame_spec = _obj(protocol.get("sampling_frame"), "sampling_frame")
    sample_spec = _obj(protocol.get("sample"), "sample")
    sample_size = _integer(sample_spec.get("issuer_clusters"), "issuer_clusters")
    sample_seed = _str(sample_spec.get("seed"), "sample.seed")
    if sample_size < 1:
        raise ReportError("issuer_clusters must be positive")
    protocol_scope = _str(protocol.get("scope"), "scope")
    index_sha = frame_spec.get("master_index_sha256")
    dataset_sha = frame_spec.get("financial_statement_dataset_sha256")
    if index_source.get("response_sha256") != index_sha:
        raise ReportError("master-index source hash differs from the protocol")
    if dataset_source.get("response_sha256") != dataset_sha:
        raise ReportError("financial dataset source hash differs from the protocol")

    index_bytes = _verified_snapshot(root, index_source, "master index")
    dataset_bytes = _verified_snapshot(root, dataset_source, "SEC submissions table")
    master_pairs: set[tuple[str, str]] = set()
    master_ciks: set[str] = set()
    master_index_filing_count = 0
    for line in index_bytes.decode("latin-1").splitlines():
        parts = line.split("|")
        if len(parts) != 5 or parts[2] != "10-K":
            continue
        accession = PurePosixPath(parts[4]).name.removesuffix(".txt")
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ReportError("master index contains an invalid 10-K accession")
        cik = _cik(parts[0])
        master_pairs.add((cik, accession))
        master_ciks.add(cik)
        master_index_filing_count += 1

    try:
        reader = csv.DictReader(
            io.StringIO(dataset_bytes.decode("utf-8"), newline=""), delimiter="\t"
        )
        if tuple(reader.fieldnames or ()) != _FRAME_COLUMNS:
            raise ReportError("SEC frame table columns do not match the pinned schema")
        dataset_rows: list[dict[str, str]] = []
        for row_index, row in enumerate(reader, start=1):
            if None in row:
                raise ReportError("SEC frame table has an extra column value")
            dataset_rows.append(
                {
                    column: _text(row.get(column), f"dataset row {row_index} {column}")
                    for column in _FRAME_COLUMNS
                }
            )
    except (UnicodeDecodeError, csv.Error) as error:
        raise ReportError("SEC frame submissions table is invalid") from error

    candidates: dict[str, list[dict[str, str]]] = defaultdict(list)
    dataset_ciks: set[str] = set()
    for row in dataset_rows:
        if row.get("form") != "10-K" or not str(row.get("filed", "")).startswith(
            "2016"
        ):
            raise ReportError("SEC frame table contains an out-of-frame row")
        cik = _cik(row.get("cik"))
        accession = str(row.get("adsh", ""))
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ReportError("SEC frame table contains an invalid accession")
        if (cik, accession) not in master_pairs:
            raise ReportError("SEC frame table filing is absent from the master index")
        dataset_ciks.add(cik)
        candidates[cik].append(row)

    if not dataset_ciks <= master_ciks:
        raise ReportError("SEC dataset contains a CIK absent from the master index")

    definitions = _obj(frame_spec.get("sic_divisions"), "sic_divisions")
    eligible: list[FrameIssuer] = []
    excluded: list[FrameExclusion] = []
    for cik in sorted(master_ciks - dataset_ciks):
        excluded.append(
            FrameExclusion(
                issuer_id=f"CIK:{cik}",
                decision_accession=None,
                countryinc=None,
                reason="no_matching_sec_xbrl_dataset_row",
            )
        )
    for cik in sorted(dataset_ciks):
        rows = candidates[cik]
        decision = min(
            rows,
            key=lambda row: (
                str(row.get("accepted", "")),
                str(row.get("adsh", "")),
            ),
        )
        country = str(decision.get("countryinc") or "").strip().upper()
        if country != "US":
            excluded.append(
                FrameExclusion(
                    issuer_id=f"CIK:{cik}",
                    decision_accession=decision["adsh"],
                    countryinc=country or None,
                    reason="non_us_or_unknown_filing_time_incorporation_country",
                )
            )
            continue
        sic = str(decision.get("sic") or "").strip() or None
        eligible.append(
            FrameIssuer(
                issuer_id=f"CIK:{cik}",
                cik=cik,
                decision_accession=decision["adsh"],
                decision_filed=_file_date(decision.get("filed"), "dataset filed"),
                report_period_end=_file_date(
                    decision.get("period"), "dataset report period"
                ),
                frame_accepted=decision["accepted"],
                countryinc=country,
                sic=sic,
                stratum=_sic_stratum(sic, definitions),
            )
        )

    expected = _obj(frame_spec.get("frame_counts"), "frame_counts")
    actual = {
        "master_index_original_10k_filings": master_index_filing_count,
        "master_index_unique_ciks": len(master_ciks),
        "matching_dataset_unique_ciks": len(dataset_ciks),
        "us_incorporated_unique_ciks": len(eligible),
        "unmatched_dataset_ciks_excluded": len(master_ciks - dataset_ciks),
        "matched_non_us_or_unknown_incorporation_ciks_excluded": len(excluded)
        - len(master_ciks - dataset_ciks),
    }
    expected_counts = {
        name: _integer(expected.get(name), f"frame_counts.{name}") for name in actual
    }
    if actual != expected_counts:
        raise ReportError(f"SEC frame counts do not match protocol: {actual}")
    return FrameSnapshot(
        protocol_scope=protocol_scope,
        sample_size=sample_size,
        sample_seed=sample_seed,
        protocol_sha256=_sha256(protocol_path.read_bytes()),
        frame_manifest_sha256=_sha256(frame_manifest_path.read_bytes()),
        eligible=tuple(eligible),
        excluded=tuple(excluded),
        frame_counts=actual,
    )


def _file_date(value: object, label: str) -> str:
    text = str(value or "")
    try:
        if re.fullmatch(r"\d{8}", text):
            return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise ReportError(f"{label} must be a valid SEC filing date") from error


def _stratum_allocation(
    populations: dict[str, int], sample_size: int
) -> dict[str, int]:
    nonempty = {name: size for name, size in populations.items() if size > 0}
    if sample_size < len(nonempty) or sample_size > sum(nonempty.values()):
        raise ReportError("requested sample size cannot cover the non-empty strata")
    allocation = {name: 1 for name in nonempty}
    remaining = sample_size - len(allocation)
    while remaining:
        active = [name for name in nonempty if allocation[name] < nonempty[name]]
        if not active:
            raise ReportError("stratum allocation exceeded its population")
        total_weight = sum(nonempty[name] for name in active)
        quotas = {name: remaining * nonempty[name] / total_weight for name in active}
        floors = {
            name: min(nonempty[name] - allocation[name], int(quotas[name]))
            for name in active
        }
        floor_total = sum(floors.values())
        for name, count in floors.items():
            allocation[name] += count
        remaining -= floor_total
        if remaining == 0:
            break
        order = sorted(
            active,
            key=lambda name: (-(quotas[name] - int(quotas[name])), name),
        )
        for name in order:
            if remaining == 0:
                break
            if allocation[name] < nonempty[name]:
                allocation[name] += 1
                remaining -= 1
    return allocation


def select_sample(frame: FrameSnapshot) -> SampleSelection:
    """Select the protocol's deterministic, proportional SIC-stratified sample."""
    size = frame["sample_size"]
    seed = frame["sample_seed"]
    groups: dict[str, list[FrameIssuer]] = defaultdict(list)
    for issuer in frame["eligible"]:
        groups[issuer["stratum"]].append(issuer)
    populations = {name: len(rows) for name, rows in groups.items()}
    allocation = _stratum_allocation(populations, size)
    selected: list[SampledIssuer] = []
    for stratum in sorted(allocation):
        ranked = sorted(
            groups[stratum],
            key=lambda issuer: (
                _sha256(f"{seed}\0{issuer['cik']}".encode("utf-8")),
                issuer["cik"],
            ),
        )
        for position, issuer in enumerate(ranked[: allocation[stratum]], start=1):
            selected.append(
                {
                    **issuer,
                    "sample_rank": position,
                    "selection_digest": _sha256(
                        f"{seed}\0{issuer['cik']}".encode("utf-8")
                    ),
                }
            )
    selected.sort(key=lambda row: (row["stratum"], row["sample_rank"], row["cik"]))
    return SampleSelection(
        selected=tuple(selected),
        population_by_stratum=dict(sorted(populations.items())),
        sample_by_stratum=dict(sorted(allocation.items())),
    )


def _source_metadata(source: CapturedSource) -> JsonObject:
    content = source.content
    return {
        "source_id": source.source_id,
        "uri": source.uri,
        "http_status": source.http_status,
        "response_bytes": len(content),
        "response_sha256": _sha256(content),
        "captured_at": _iso(source.captured_at or source.available_at),
        "response_headers": dict(source.response_headers),
    }


def _filing_records(raw_sources: list[JsonObject]) -> list[JsonObject]:
    merged: dict[str, JsonObject] = {}
    for raw in raw_sources:
        filings = _obj(raw.get("filings"), "submissions.filings")
        recent = _obj(filings.get("recent"), "submissions.recent")
        keys = (
            "form",
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
        )
        arrays = {
            key: _list(recent.get(key), f"submissions.recent.{key}") for key in keys
        }
        lengths = {len(value) for value in arrays.values()}
        if len(lengths) != 1:
            raise ReportError("SEC submissions arrays have inconsistent lengths")
        count = lengths.pop()
        for index in range(count):
            form = arrays["form"][index]
            accession = arrays["accessionNumber"][index]
            if not isinstance(form, str) or form not in _ANNUAL_FORMS:
                continue
            if not isinstance(accession, str) or not re.fullmatch(
                r"\d{10}-\d{2}-\d{6}", accession
            ):
                continue
            record: JsonObject = {
                "accession_number": accession,
                "form": form,
                "filing_date": _text(
                    arrays["filingDate"][index], "submissions filingDate"
                ),
                "report_period_end": _text(
                    arrays["reportDate"][index], "submissions reportDate"
                ),
                "accepted_at": _text(
                    arrays["acceptanceDateTime"][index],
                    "submissions acceptanceDateTime",
                ),
            }
            previous = merged.get(accession)
            if previous is not None and previous != record:
                raise ReportError(
                    "SEC submissions snapshots conflict for one accession"
                )
            merged[accession] = record
    return sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("report_period_end") or ""),
            str(row.get("accepted_at") or ""),
            row["accession_number"],
        ),
    )


def _normalized_company_facts(raw: JsonObject) -> JsonObject:
    raw_facts = _obj(raw.get("facts"), "companyfacts.facts")
    us_gaap = raw_facts.get("us-gaap")
    if not isinstance(us_gaap, dict):
        raise ReportError("SEC Company Facts response has no us-gaap taxonomy")
    kept: dict[str, object] = {}
    for field, (concept_name, unit, _period_type) in FIELD_SPECS.items():
        concept = us_gaap.get(concept_name)
        if not isinstance(concept, dict):
            continue
        units = concept.get("units")
        if not isinstance(units, dict) or not isinstance(units.get(unit), list):
            continue
        records: list[JsonObject] = []
        for record_value in _list(units[unit], f"{concept_name}.{unit}"):
            record = _obj(record_value, f"{concept_name} fact")
            form = record.get("form")
            if not isinstance(form, str) or form not in _ANNUAL_FORMS:
                continue
            records.append(
                {key: record[key] for key in _FACT_ROW_KEYS if key in record}
            )
        kept[concept_name] = {
            "label": concept.get("label"),
            "units": {unit: records},
        }
    return {
        "cik": raw.get("cik"),
        "entityName": raw.get("entityName"),
        "facts": {"us-gaap": kept},
    }


def _submission_file_uris(raw: JsonObject) -> tuple[str, ...]:
    files = _obj(raw.get("filings"), "submissions.filings").get("files", [])
    file_rows = _list(files, "submissions.filings.files")
    uris: list[str] = []
    for item in file_rows:
        record = _obj(item, "submissions.file")
        name = record.get("name")
        if not isinstance(name, str) or not re.fullmatch(
            r"CIK\d+-submissions-\d+\.json", name
        ):
            raise ReportError("SEC submissions history contains an invalid filename")
        filing_to = record.get("filingTo")
        if isinstance(filing_to, str) and filing_to < "2009-01-01":
            continue
        uris.append(f"https://data.sec.gov/submissions/{name}")
    return tuple(sorted(set(uris)))


def _capture_issuer(
    adapter: SecEdgarSourceAdapter,
    issuer: SampledIssuer,
    *,
    protocol_sha256: str,
    frame_manifest_sha256: str,
) -> JsonObject:
    cik = issuer["cik"]
    base = adapter.capture_submissions(cik)
    base_payload = _obj(json.loads(base.content), "SEC submissions")
    if _cik(base_payload.get("cik")) != cik:
        raise ReportError("SEC submissions CIK differs from the selected issuer")
    sources = [base]
    submission_payloads = [base_payload]
    for uri in _submission_file_uris(base_payload):
        archived = adapter.capture_json(source_id="sec-submissions", uri=uri)
        archived_payload = _obj(json.loads(archived.content), "SEC submissions archive")
        if _cik(archived_payload.get("cik")) != cik:
            raise ReportError("SEC submissions history CIK differs from the issuer")
        sources.append(archived)
        submission_payloads.append(archived_payload)
    company_source = adapter.capture_company_facts(cik)
    company_payload = _obj(json.loads(company_source.content), "SEC Company Facts")
    if _cik(company_payload.get("cik")) != cik:
        raise ReportError("SEC Company Facts CIK differs from the selected issuer")
    filings = _filing_records(submission_payloads)
    decision_present = any(
        row["accession_number"] == issuer["decision_accession"]
        and row["form"] == "10-K"
        for row in filings
    )
    return {
        "schema_version": "issue-359-issuer-snapshot-v1",
        "issuer_id": issuer["issuer_id"],
        "cik": cik,
        "decision_accession": issuer["decision_accession"],
        "protocol_sha256": protocol_sha256,
        "frame_manifest_sha256": frame_manifest_sha256,
        "captured_at": _iso(datetime.now(UTC)),
        "decision_filing_present": decision_present,
        "filings": filings,
        "companyfacts": _normalized_company_facts(company_payload),
        "source_responses": [
            _source_metadata(source) for source in [*sources, company_source]
        ],
    }


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


def _write_capture_manifest(path: Path, manifest: JsonObject) -> None:
    _write_atomic(path, _canonical_json(manifest))


def _snapshot_source_hashes(snapshot: JsonObject) -> list[str]:
    sources = _list(snapshot.get("source_responses"), "snapshot source_responses")
    return [
        _str(
            _obj(source, "snapshot source").get("response_sha256"),
            "source response sha256",
        )
        for source in sources
    ]


def _snapshot_decision_status(snapshot: JsonObject) -> str:
    decision_present = snapshot.get("decision_filing_present")
    if not isinstance(decision_present, bool):
        raise ReportError("issuer snapshot decision_filing_present must be boolean")
    return "captured" if decision_present else "decision_filing_missing"


def capture_cohort(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    frame_manifest_path: Path = DEFAULT_FRAME_MANIFEST,
    capture_manifest_path: Path = DEFAULT_CAPTURE_MANIFEST,
    adapter: SecEdgarSourceAdapter | None = None,
    root: Path = ROOT,
) -> JsonObject:
    frame = load_frame(protocol_path, frame_manifest_path, root=root)
    sample = select_sample(frame)
    if adapter is None:
        user_agent = os.environ.get("FUNDAMENTAL_SEC_USER_AGENT", "")
        adapter = SecEdgarSourceAdapter(
            SecRequestPolicy(
                user_agent=user_agent,
                min_interval_seconds=0.12,
                timeout_seconds=45.0,
                max_response_bytes=64_000_000,
            )
        )
    capture_manifest_path = capture_manifest_path.resolve()
    existing = (
        _read_json(capture_manifest_path) if capture_manifest_path.exists() else None
    )
    protocol_sha256 = frame["protocol_sha256"]
    frame_sha256 = frame["frame_manifest_sha256"]
    if existing is not None and (
        existing.get("protocol_sha256") != protocol_sha256
        or existing.get("frame_manifest_sha256") != frame_sha256
    ):
        raise ReportError("existing capture manifest belongs to a different protocol")
    prior: dict[str, JsonObject] = {}
    if existing is not None:
        for row_index, row_value in enumerate(
            _list(existing.get("issuers"), "capture manifest issuers")
        ):
            row = _obj(row_value, f"capture manifest issuer {row_index}")
            prior[_str(row.get("cik"), "capture issuer cik")] = row
        capture_started_at = _str(
            existing.get("capture_started_at"), "capture_started_at"
        )
    else:
        capture_started_at = _iso(datetime.now(UTC))
    records: list[JsonObject] = []
    output_dir = capture_manifest_path.parent
    snapshot_dir = output_dir / "snapshots"
    for selected in sample["selected"]:
        cik = selected["cik"]
        path = snapshot_dir / f"{cik}.json.gz"
        previous = prior.get(cik, {})
        row: JsonObject = {
            **selected,
            "capture_status": "pending",
            "snapshot_path": str(path.resolve().relative_to(root.resolve())),
            "snapshot_sha256": None,
            "snapshot_bytes": None,
            "source_response_sha256s": [],
            "failure_code": None,
        }
        if path.exists():
            packed = path.read_bytes()
            try:
                snapshot = _obj(
                    json.loads(gzip.decompress(packed)), "existing issuer snapshot"
                )
            except (OSError, EOFError, json.JSONDecodeError) as error:
                raise ReportError(
                    f"existing issuer snapshot is corrupt: {cik}"
                ) from error
            if (
                snapshot.get("protocol_sha256") != protocol_sha256
                or snapshot.get("frame_manifest_sha256") != frame_sha256
                or snapshot.get("cik") != cik
                or snapshot.get("decision_accession") != selected["decision_accession"]
            ):
                raise ReportError(
                    f"existing issuer snapshot does not match sample: {cik}"
                )
            row.update(
                {
                    "capture_status": _snapshot_decision_status(snapshot),
                    "snapshot_sha256": _sha256(packed),
                    "snapshot_bytes": len(packed),
                    "source_response_sha256s": _snapshot_source_hashes(snapshot),
                }
            )
            if previous.get("capture_status") == "retrieval_failed":
                row["failure_code"] = None
        else:
            try:
                snapshot = _capture_issuer(
                    adapter,
                    selected,
                    protocol_sha256=protocol_sha256,
                    frame_manifest_sha256=frame_sha256,
                )
                packed = gzip.compress(_canonical_json(snapshot), mtime=0)
                if path.exists() and path.read_bytes() != packed:
                    raise ReportError(f"issuer snapshot cannot be replaced: {cik}")
                _write_atomic(path, packed)
                row.update(
                    {
                        "capture_status": _snapshot_decision_status(snapshot),
                        "snapshot_sha256": _sha256(packed),
                        "snapshot_bytes": len(packed),
                        "source_response_sha256s": _snapshot_source_hashes(snapshot),
                    }
                )
            except SecSourceError as error:
                row.update(
                    {"capture_status": "retrieval_failed", "failure_code": error.code}
                )
            except OSError:
                row.update(
                    {
                        "capture_status": "retrieval_failed",
                        "failure_code": "SOURCE_UNAVAILABLE",
                    }
                )
            except (ValueError, ReportError, json.JSONDecodeError):
                row.update(
                    {
                        "capture_status": "snapshot_invalid",
                        "failure_code": "INVALID_SOURCE_SNAPSHOT",
                    }
                )
        records.append(row)
        manifest: JsonObject = {
            "schema_version": "issue-359-cohort-capture-v1",
            "cohort_id": "sec-2016q1-us-10k-sic-stratified-v1",
            "capture_started_at": capture_started_at,
            "protocol_path": str(protocol_path.resolve().relative_to(root.resolve())),
            "protocol_sha256": protocol_sha256,
            "frame_manifest_path": str(
                frame_manifest_path.resolve().relative_to(root.resolve())
            ),
            "frame_manifest_sha256": frame_sha256,
            "frame_counts": frame["frame_counts"],
            "population_by_stratum": sample["population_by_stratum"],
            "sample_by_stratum": sample["sample_by_stratum"],
            "selected_issuer_clusters": len(sample["selected"]),
            "issuers": [*records]
            + [
                {
                    **remaining,
                    "capture_status": "pending",
                    "snapshot_path": str(
                        (snapshot_dir / f"{remaining['cik']}.json.gz").relative_to(
                            root.resolve()
                        )
                    ),
                    "snapshot_sha256": None,
                    "snapshot_bytes": None,
                    "source_response_sha256s": [],
                    "failure_code": None,
                }
                for remaining in sample["selected"][len(records) :]
            ],
        }
        manifest["status"] = (
            "complete"
            if all(item["capture_status"] == "captured" for item in manifest["issuers"])
            else "partial"
        )
        _write_capture_manifest(capture_manifest_path, manifest)
    return manifest


def _filings_for_report(snapshot: JsonObject, issuer_id: str) -> tuple[Filing, ...]:
    records = _list(snapshot.get("filings"), "issuer snapshot filings")
    recent = {
        "form": [],
        "accessionNumber": [],
        "reportDate": [],
        "acceptanceDateTime": [],
    }
    for record in records:
        record = _obj(record, "issuer snapshot filing")
        recent["form"].append(record.get("form"))
        recent["accessionNumber"].append(record.get("accession_number"))
        recent["reportDate"].append(record.get("report_period_end"))
        recent["acceptanceDateTime"].append(record.get("accepted_at"))
    raw = {"filings": {"recent": recent}}
    from .history_sufficiency_report import _submissions

    return _submissions(raw, issuer_id)


def _measure_decision(
    model_id: str,
    fields: tuple[str, ...],
    decision: Filing,
    filings: tuple[Filing, ...],
    facts: tuple[Fact, ...],
) -> JsonObject:
    as_of = decision.accepted_at
    periods = sorted(
        {
            filing.period_end
            for filing in filings
            if filing.form == "10-K"
            and filing.accepted_at <= as_of
            and filing.period_end <= decision.period_end
        }
    )
    window = periods[-WINDOW:]
    coverage: list[JsonObject] = []
    fact_catalog: dict[str, dict[str, str]] = {}
    for period in window:
        present: list[str] = []
        fact_ids: list[str] = []
        for field in fields:
            fact = _select_fact(facts, field, period, as_of)
            if fact is None:
                continue
            reference = _fact_reference(fact)
            fact_catalog[reference["fact_id"]] = reference
            present.append(field)
            fact_ids.append(reference["fact_id"])
        coverage.append(
            {
                "period_end": period.isoformat(),
                "present_fields": present,
                "missing_fields": [field for field in fields if field not in present],
                "source_fact_ids": fact_ids,
            }
        )
    field_counts = {
        field: sum(field in row["present_fields"] for row in coverage)
        for field in fields
    }
    complete_periods = sum(not row["missing_fields"] for row in coverage)
    passes = len(window) == WINDOW and complete_periods >= MINIMUM_PERIODS
    next_filing = first_subsequent_original_filing(decision, filings)
    label_fields: list[str] = []
    label_fact_ids: list[str] = []
    if next_filing is not None:
        for field in fields:
            fact = _select_fact(
                facts,
                field,
                next_filing.period_end,
                next_filing.accepted_at,
                next_filing.accession,
            )
            if fact is None:
                continue
            label_fields.append(field)
            reference = _fact_reference(fact)
            fact_catalog[reference["fact_id"]] = reference
            label_fact_ids.append(reference["fact_id"])
    return {
        "model_id": model_id,
        "status": "measured" if len(window) == WINDOW else "fewer_than_five_periods",
        "issuer_id": decision.issuer_id,
        "decision_accession": decision.accession,
        "report_period_end": decision.period_end.isoformat(),
        "available_at": _iso(decision.accepted_at),
        "valuation_timestamp": _iso(as_of),
        "history_window_period_ends": [period.isoformat() for period in window],
        "history_period_gaps": _history_period_gaps(window),
        "period_field_coverage": coverage,
        "field_period_counts": field_counts,
        "complete_history_periods": complete_periods,
        "candidate_rule_passes": passes,
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
        "next_label_complete": next_filing is not None
        and len(label_fields) == len(fields),
        "fact_catalog": [fact_catalog[key] for key in sorted(fact_catalog)],
    }


def _binary_summary(successes: int, trials: int) -> JsonObject:
    return {
        "successes": successes,
        "trials": trials,
        "rate": round(successes / trials, 6) if trials else None,
        "wilson_95": _wilson(successes, trials),
    }


def build_cohort_report(
    capture_manifest_path: Path = DEFAULT_CAPTURE_MANIFEST,
    *,
    root: Path = ROOT,
) -> JsonObject:
    capture_manifest_path = capture_manifest_path.resolve()
    capture = _read_json(capture_manifest_path)
    protocol_path = _repo_path(root, capture.get("protocol_path"), "sampling protocol")
    frame_manifest_path = _repo_path(
        root, capture.get("frame_manifest_path"), "frame manifest"
    )
    frame = load_frame(protocol_path, frame_manifest_path, root=root)
    sample = select_sample(frame)
    if capture.get("protocol_sha256") != frame["protocol_sha256"]:
        raise ReportError("capture manifest protocol hash mismatch")
    if capture.get("frame_manifest_sha256") != frame["frame_manifest_sha256"]:
        raise ReportError("capture manifest frame hash mismatch")
    source_rows = _list(capture.get("issuers"), "capture manifest issuers")
    if len(source_rows) != len(sample["selected"]):
        raise ReportError("capture manifest must retain all selected issuer clusters")
    by_cik: dict[str, JsonObject] = {}
    for row_index, row_value in enumerate(source_rows):
        row = _obj(row_value, f"capture issuer {row_index}")
        cik = _str(row.get("cik"), "capture issuer cik")
        if cik in by_cik:
            raise ReportError("capture manifest contains a duplicate issuer CIK")
        by_cik[cik] = row
    if set(by_cik) != {item["cik"] for item in sample["selected"]}:
        raise ReportError(
            "capture manifest issuer set differs from deterministic sample"
        )

    issuer_reports: list[JsonObject] = []
    model_rows: dict[str, list[JsonObject]] = {name: [] for name in MODEL_FIELDS}
    fact_catalog: dict[str, dict[str, str]] = {}
    for selected in sample["selected"]:
        captured = by_cik[selected["cik"]]
        status = _str(captured.get("capture_status"), "capture status")
        source_hashes = [
            _str(value, "source response sha256")
            for value in _list(
                captured.get("source_response_sha256s", []),
                "capture source_response_sha256s",
            )
        ]
        base: JsonObject = {
            **selected,
            "capture_status": status,
            "source_response_sha256s": source_hashes,
        }
        snapshot: JsonObject | None = None
        if status in {"captured", "decision_filing_missing"}:
            path = _repo_path(root, captured.get("snapshot_path"), "issuer snapshot")
            packed = path.read_bytes()
            if _sha256(packed) != captured.get("snapshot_sha256"):
                raise ReportError(f"issuer snapshot hash mismatch: {selected['cik']}")
            try:
                snapshot = _obj(json.loads(gzip.decompress(packed)), "issuer snapshot")
            except (OSError, EOFError, json.JSONDecodeError) as error:
                raise ReportError(
                    f"issuer snapshot is invalid: {selected['cik']}"
                ) from error
            if (
                snapshot.get("cik") != selected["cik"]
                or snapshot.get("decision_accession") != selected["decision_accession"]
            ):
                raise ReportError(
                    f"issuer snapshot identity mismatch: {selected['cik']}"
                )
        error_detail = None
        filings: tuple[Filing, ...] = ()
        facts: tuple[Fact, ...] = ()
        decision: Filing | None = None
        if snapshot is not None and status == "captured":
            try:
                filings = _filings_for_report(snapshot, selected["issuer_id"])
                decision = next(
                    (
                        filing
                        for filing in filings
                        if filing.accession == selected["decision_accession"]
                        and filing.form == "10-K"
                    ),
                    None,
                )
                if decision is None:
                    error_detail = "decision_accession_missing_from_submission_history"
                else:
                    facts = _company_facts(
                        _obj(snapshot.get("companyfacts"), "issuer companyfacts"),
                        filings,
                    )
            except (KeyError, ReportError, ValueError) as error:
                error_detail = f"invalid_or_incomplete_evidence:{type(error).__name__}"
        elif status == "decision_filing_missing":
            error_detail = "decision_accession_missing_from_submission_history"
        else:
            error_detail = captured.get("failure_code") or status

        model_statuses: dict[str, str] = {}
        for model_id, fields in MODEL_FIELDS.items():
            if decision is None:
                detail: JsonObject = {
                    "model_id": model_id,
                    "status": "unmeasured_missing_decision_or_snapshot",
                    "issuer_id": selected["issuer_id"],
                    "decision_accession": selected["decision_accession"],
                    "candidate_rule_passes": False,
                    "complete_history_periods": 0,
                    "field_period_counts": {field: 0 for field in fields},
                    "next_original_filing_accession": None,
                    "next_label_complete": False,
                    "next_label_fields_present": [],
                    "fact_catalog": [],
                }
            else:
                detail = _measure_decision(model_id, fields, decision, filings, facts)
            model_rows[model_id].append(detail)
            model_statuses[model_id] = _str(detail.get("status"), "model status")
            for fact_value in _list(detail.get("fact_catalog", []), "fact_catalog"):
                fact = _obj(fact_value, "fact catalog entry")
                fact_id = _str(fact.get("fact_id"), "fact_id")
                fact_catalog[fact_id] = {
                    key: _str(value, f"fact_catalog.{key}")
                    for key, value in fact.items()
                }
        base["row_status"] = (
            "measured" if decision is not None else "excluded_from_measurement"
        )
        base["exclusion_reason"] = error_detail
        base["model_statuses"] = model_statuses
        issuer_reports.append(base)

    model_reports: dict[str, object] = {}
    sample_count = len(sample["selected"])
    for model_id, fields in MODEL_FIELDS.items():
        rows = model_rows[model_id]
        history_pass = [row.get("candidate_rule_passes") is True for row in rows]
        next_available = [
            bool(row.get("next_original_filing_accession")) for row in rows
        ]
        label_complete = [bool(row.get("next_label_complete")) for row in rows]
        gate_rows = [
            row
            for row in rows
            if row["candidate_rule_passes"]
            and row.get("next_original_filing_accession")
        ]
        field_coverage = {}
        label_field_coverage = {}
        for field in fields:
            count_by_issuer = [
                _integer(
                    _obj(row.get("field_period_counts"), "field_period_counts").get(
                        field, 0
                    ),
                    f"field_period_counts.{field}",
                )
                for row in rows
            ]
            field_coverage[field] = {
                "issuers_with_at_least_three_periods": _binary_summary(
                    sum(count >= MINIMUM_PERIODS for count in count_by_issuer),
                    sample_count,
                ),
                "period_observations": sum(count_by_issuer),
                "possible_issuer_periods": sample_count * WINDOW,
            }
            label_field_count = sum(
                field
                in _list(
                    row.get("next_label_fields_present", []),
                    "next_label_fields_present",
                )
                for row in rows
            )
            label_field_coverage[field] = _binary_summary(
                label_field_count, sample_count
            )
        gate_complete = sum(bool(row.get("next_label_complete")) for row in gate_rows)
        complete_count = sum(label_complete)
        model_reports[model_id] = {
            "fields": [
                {"field_id": field, "concept": FIELD_SPECS[field][0]}
                for field in fields
            ],
            "issuer_clusters_in_denominator": sample_count,
            "issuer_clusters_measured": sum(
                row["status"] == "measured" for row in rows
            ),
            "candidate_rule": {
                "rule": f"at least {MINIMUM_PERIODS} complete periods in the latest {WINDOW} original annual filing periods",
                "eligibility": _binary_summary(sum(history_pass), sample_count),
                "threshold_status": "candidate_not_validated_by_forecast_accuracy",
            },
            "field_coverage": field_coverage,
            "first_subsequent_original_filing_available": _binary_summary(
                sum(next_available), sample_count
            ),
            "complete_first_subsequent_labels": _binary_summary(
                complete_count, sample_count
            ),
            "complete_labels_conditional_on_next_filing": _binary_summary(
                sum(
                    complete and available
                    for complete, available in zip(
                        label_complete, next_available, strict=True
                    )
                ),
                sum(next_available),
            ),
            "candidate_gate_oos": {
                "candidate_eligible_with_next_filing": len(gate_rows),
                "complete_labels": gate_complete,
                "completeness": _binary_summary(gate_complete, len(gate_rows)),
            },
            "next_label_field_coverage": label_field_coverage,
            "decision_rows": rows,
            "forecast_accuracy": "not_measured_no_historical_fundamental_service_forecasts",
        }

    captured_count = sum(row["row_status"] == "measured" for row in issuer_reports)
    threshold_status = (
        "underpowered"
        if sample_count < 100 or captured_count < 100
        else "history_evidence_measured_threshold_review_required"
    )
    return {
        "schema_version": "issue-359-history-threshold-report-v1",
        "cohort_id": capture.get("cohort_id"),
        "capture_manifest": {
            "path": str(capture_manifest_path.resolve().relative_to(root.resolve())),
            "sha256": _sha256(capture_manifest_path.read_bytes()),
            "captured_at": capture.get("capture_started_at"),
            "status": capture.get("status"),
        },
        "protocol": {
            "path": str(protocol_path.resolve().relative_to(root.resolve())),
            "sha256": frame["protocol_sha256"],
        },
        "frame_manifest": {
            "path": str(frame_manifest_path.resolve().relative_to(root.resolve())),
            "sha256": frame["frame_manifest_sha256"],
        },
        "sampling": {
            "sampling_frame": frame["protocol_scope"],
            "frame_counts": frame["frame_counts"],
            "eligible_issuer_clusters": len(frame["eligible"]),
            "excluded_issuer_clusters": len(frame["excluded"]),
            "population_by_stratum": sample["population_by_stratum"],
            "sample_by_stratum": sample["sample_by_stratum"],
            "selected_issuer_clusters": sample_count,
            "issuer_identity": "CIK; one decision and one sample unit per issuer cluster",
        },
        "source_exclusions": [
            "current ticker lists and current survival status",
            "analyst estimates, analyst targets, and consensus",
            "Search results and LLM-extracted values",
        ],
        "issuer_rows": issuer_reports,
        "models": model_reports,
        "threshold_decision": {
            "status": threshold_status,
            "supported_history_threshold": None,
            "candidate_rule": "three complete annual periods in the latest five",
            "forecast_error": "not measured; no valuation-accuracy or calibration claim",
            "reason": "coverage and first-subsequent filing evidence are reported separately; a history threshold remains a candidate until the declared evidence is reviewed for both released models",
            "affected_results": "provisional_or_abstained_until_threshold_review",
        },
        "source_fact_catalog": [fact_catalog[key] for key in sorted(fact_catalog)],
    }


def write_report(report: JsonObject, output_path: Path = DEFAULT_REPORT) -> bool:
    payload = _canonical_json(report)
    if output_path.exists() and output_path.read_bytes() == payload:
        return False
    _write_atomic(output_path, payload)
    return True


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    capture_parser.add_argument(
        "--frame-manifest", type=Path, default=DEFAULT_FRAME_MANIFEST
    )
    capture_parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_CAPTURE_MANIFEST
    )
    report_parser = subparsers.add_parser("report")
    report_parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_CAPTURE_MANIFEST
    )
    report_parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            result = capture_cohort(
                protocol_path=args.protocol,
                frame_manifest_path=args.frame_manifest,
                capture_manifest_path=args.manifest,
            )
            captured = sum(
                row["capture_status"] == "captured" for row in result["issuers"]
            )
            print(
                json.dumps(
                    {
                        "manifest": str(args.manifest),
                        "manifest_sha256": _sha256(args.manifest.read_bytes()),
                        "selected_issuer_clusters": result["selected_issuer_clusters"],
                        "captured_issuer_clusters": captured,
                        "status": result["status"],
                    },
                    sort_keys=True,
                )
            )
            return 0 if result["status"] == "complete" else 2
        report = build_cohort_report(args.manifest)
        wrote = write_report(report, args.output)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "sha256": _sha256(args.output.read_bytes()),
                    "threshold_status": report["threshold_decision"]["status"],
                    "wrote": wrote,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ReportError, SecSourceError, ValueError, KeyError) as error:
        print(f"history cohort {args.command} failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
