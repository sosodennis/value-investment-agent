"""Fixed batch identity, original evidence boundaries and resumable publication."""

from __future__ import annotations

import base64
import copy
import gzip
import json
import sys
from pathlib import Path

import pytest

from fundamental_service.arelle_parser import ArelleFindingV1
from fundamental_service.accounting_fields import (
    AccountingFieldRequestV1,
    extract_accounting_fields,
)
from fundamental_service.automatic_mapping import automatic_mapping_proposals
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_original_issuer import evaluate, original

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import batch_history_study as batch  # noqa: E402
from read_history_originals import OriginalReader, checked_document  # noqa: E402


def test_declared_revenue_alternatives_are_provisional_and_source_bound():
    claim = evaluate()
    proposals = automatic_mapping_proposals(
        "revenue", mapping_version="test-v1", original=claim
    )
    assert {p.source_concept for p in proposals} == {
        "us-gaap:Revenues",
        "us-gaap:SalesRevenueNet",
    }
    assert all(
        p.status == "provisional"
        and p.reviewer is None
        and p.confidence == "unresolved"
        for p in proposals
    )
    request = AccountingFieldRequestV1(
        original=claim, normalized_fields=("revenue",), mapping_version="test-v1"
    )
    packet = extract_accounting_fields(request)
    row = packet.fields[0]
    assert row.candidate_count == 1
    fact = row.candidates[0]
    assert fact.concept == "us-gaap:SalesRevenueNet" and fact.value == 100
    assert fact.source.content_hash == claim.source.content_hash
    assert fact.accession_number == claim.source.accession_number
    assert fact.mapping.status == "provisional" and fact.security_id is None
    assert packet == extract_accounting_fields(request)


def test_conflicting_observations_and_dimensions_are_all_retained():
    report, source = original()
    revenue = report.facts[-1]
    observations = (
        revenue.model_copy(update={"value": "999", "context_id": "conflict"}),
        revenue.model_copy(
            update={"context_id": "segment", "dimensions": (("ex:Region", "ex:US"),)}
        ),
    )
    claim = evaluate_original_issuer(
        report.model_copy(update={"facts": (*report.facts, *observations)}),
        source=source,
        decision_at=batch.timestamp("2026-03-01T00:00:00Z"),
    )
    row = extract_accounting_fields(
        AccountingFieldRequestV1(
            original=claim, normalized_fields=("revenue",), mapping_version="test-v1"
        )
    ).fields[0]
    assert row.candidate_count == 3
    assert len({c.candidate_id for c in row.candidates}) == 3
    assert {c.value for c in row.candidates} == {100, 999}
    assert any(c.dimensions for c in row.candidates)
    assert len(row.conflicts) == 1
    assert len(row.conflicts[0].candidate_ids) == 2


def test_parser_blocker_prevents_mapping_but_retains_original_severity():
    report, source = original()
    claim = evaluate(
        report.model_copy(
            update={
                "finding_codes": ("DQC.test",),
                "findings": (
                    ArelleFindingV1(
                        code="DQC.test",
                        message="retained",
                        severity="warning",
                        rule_severity="error",
                    ),
                ),
            }
        ),
        source,
    )
    packet = extract_accounting_fields(
        AccountingFieldRequestV1(
            original=claim,
            normalized_fields=(*batch.CORE_FIELDS, *batch.PARENT_CONCEPTS),
            mapping_version="test-v1",
        )
    )
    assert packet.parser_blocking_codes == ("DQC.test",)
    assert all(row.candidate_count == 0 for row in packet.fields)
    assert all("PARSER_VALIDATION_BLOCKED" in row.issue_codes for row in packet.fields)
    assert claim.report.findings[0].rule_severity == "error"


@pytest.mark.parametrize(
    "mutation",
    ["issuer", "accession", "period", "availability", "amendment", "decision"],
)
def test_supplement_cannot_replace_fixed_identity(mutation):
    claim = evaluate()
    target = {
        "cik": claim.source.cik,
        "accession": claim.source.accession_number,
        "form": "10-K",
        "accepted_at": claim.source.available_at.isoformat(),
        "valuation_timestamp": claim.decision_at.isoformat(),
        "period_end": "2025-12-31",
    }
    batch.check_original(claim, target)
    target.update(
        {
            {
                "issuer": "cik",
                "accession": "accession",
                "period": "period_end",
                "availability": "accepted_at",
                "amendment": "form",
                "decision": "valuation_timestamp",
            }[mutation]: {
                "issuer": "0000000002",
                "accession": "0000000001-26-000002",
                "period": "2024-12-31",
                "availability": "2026-02-02T00:00:00Z",
                "amendment": "10-K/A",
                "decision": "2026-03-02T00:00:00Z",
            }[mutation]
        }
    )
    with pytest.raises(batch.DesignError, match="differs"):
        batch.check_original(claim, target)


@pytest.mark.parametrize("mutation", ["digest", "length", "canonical", "duplicate"])
def test_reader_rejects_corrupted_or_ambiguous_json(mutation, monkeypatch):
    raw = canonical_bytes({"value": 1})
    if mutation == "canonical":
        raw = b'{"value": 1}'
    if mutation == "duplicate":
        raw = b'{"value":1,"value":2}'
    ref = {
        "sha256": sha256_digest(json.loads(raw)),
        "bytes": len(raw),
        "storage": "canonical-json-gzip",
        "path": "ignored",
    }
    if mutation in ("canonical", "duplicate"):
        ref["sha256"] = batch.digest(raw)
    if mutation == "digest":
        ref["sha256"] = "0" * 64
    if mutation == "length":
        ref["bytes"] += 1
    monkeypatch.setattr(
        OriginalReader, "packed", lambda *_: gzip.compress(raw, mtime=0)
    )
    with pytest.raises(batch.DesignError):
        OriginalReader(Path("ignored")).document(ref)


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "docs/other.json.gz",
        "docs/acceptance/issue-361-marker62-evidence-v1/../escape",
    ],
)
def test_reader_rejects_unsafe_references_before_git(path):
    with pytest.raises(batch.DesignError, match="unsafe"):
        OriginalReader(Path("ignored")).packed(path)


@pytest.mark.parametrize("mutation", [None, "offset", "payload", "order"])
def test_reader_reconstructs_chunks_and_checks_each_pin(monkeypatch, mutation):
    raw = canonical_bytes({"original": "retained"})
    documents, chunks = {}, []
    offset = 0
    for i, piece in enumerate((raw[:10], raw[10:])):
        chunk = canonical_bytes({"content_base64": base64.b64encode(piece).decode()})
        path = f"chunk{i}"
        documents[path] = gzip.compress(chunk, mtime=0)
        chunks.append(
            {
                "path": path,
                "sha256": batch.digest(chunk),
                "offset": offset,
                "bytes": len(piece),
                "content_sha256": batch.digest(piece),
            }
        )
        offset += len(piece)
    ref = {
        "sha256": batch.digest(raw),
        "bytes": len(raw),
        "storage": "canonical-json-chunks",
        "chunks": chunks,
    }
    if mutation == "offset":
        chunks[1]["offset"] += 1
    if mutation == "payload":
        chunks[0]["content_sha256"] = "0" * 64
    if mutation == "order":
        chunks.reverse()
    monkeypatch.setattr(OriginalReader, "packed", lambda _, path: documents[path])
    reader = OriginalReader(Path("ignored"))
    if mutation:
        with pytest.raises(batch.DesignError):
            reader.document(ref)
    else:
        assert reader.document(ref) == {"original": "retained"}


@pytest.fixture
def cohort(monkeypatch):
    issuers, targets, refs, records = [], [], [], {}
    for i in range(100):
        cik = str(i + 1).zfill(10)
        target_rows = []
        count = 6 if i < 89 else 5
        for j in range(count):
            role = (
                "label"
                if j == count - 1
                else "decision"
                if j == count - 2
                else "history"
            )
            year = 2017 if role == "label" else 2016 if role == "decision" else 2011 + j
            accession = f"{cik}-{str(year)[2:]}-000001"
            at = f"{year}-02-01T00:00:00Z"
            target = {
                "issuer_id": f"CIK:{cik}",
                "cik": cik,
                "accession": accession,
                "accepted_at": at,
                "valuation_timestamp": at
                if role == "label"
                else "2016-02-01T00:00:00Z",
                "period_end": f"{year - 1}-12-31",
                "form": "10-K",
                "role": role,
            }
            inputs = {
                "target": target,
                "pins": {"source_commit": batch.PARSER_EXECUTION},
            }
            output = {
                "status": "refused",
                "code": "RETAINED_PARSER_REFUSAL",
                "canonical_release_published": False,
                "canonical_snapshot_published": False,
            }
            record = {
                "inputs": inputs,
                "output": output,
                "input_digest": sha256_digest(inputs),
                "output_digest": sha256_digest(output),
            }
            identity = sha256_digest(record)
            records[identity] = record
            refs.append({"sha256": identity})
            target_rows.append(target)
        targets.extend(target_rows)
        issuers.append(
            {
                "issuer_id": f"CIK:{cik}",
                "decision_at": "2016-02-01T00:00:00Z",
                "decision_accession": target_rows[-2]["accession"],
                "label_accession": target_rows[-1]["accession"],
            }
        )
    manifest = {
        "issuer_decisions": issuers,
        "original_inventory": {"targets": targets},
        "original_filing_outcome_refs": refs,
    }
    monkeypatch.setattr(batch, "MANIFEST_DIGEST", sha256_digest(manifest))
    index = batch.BatchIndex(
        schema_version="history-study-batch-index.v1",
        fixed_manifest_digest=batch.MANIFEST_DIGEST,
        runtime=batch.runtime_pins(),
    )

    class Reader:
        revision = batch.SOURCE_REVISION

        def document(self, ref):
            return records[ref["sha256"]]

    return manifest, index, Reader()


def test_first10_and_full100_have_identical_issuer_artifacts_and_retain_all_failures(
    cohort, tmp_path
):
    manifest, index, reader = cohort
    small, small_artifacts = batch.prepare_batch(
        manifest, index, tmp_path, reader, exact_commit="a" * 40, limit=10
    )
    full, full_artifacts = batch.prepare_batch(
        manifest, index, tmp_path, reader, exact_commit="a" * 40
    )
    assert small["issuers"] == full["issuers"][:10]
    assert all(full_artifacts[key] == raw for key, raw in small_artifacts.items())
    assert (
        full["processed_issuer_count"] == 100 and full["processed_filing_count"] == 589
    )
    assert (
        sum(sum(row["retained_failure_counts"].values()) for row in full["issuers"])
        == 589
    )
    assert (
        full["independent_conditional_issuers"] == 0
        and full["supported_history_threshold"] is None
    )
    packet = json.loads(next(iter(full_artifacts.values())))
    assert len(packet["output"]["arms"]) == 6
    assert all(row["status"] == "abstain" for row in packet["output"]["arms"])
    assert packet["input_digest"] == sha256_digest(packet["inputs"])
    assert packet["inputs"]["retained_result_digests"]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "omitted",
        "substitution",
        "envelope",
        "execution",
        "future",
        "label",
    ],
)
def test_invalid_fixed_evidence_fails_before_publication(
    cohort, tmp_path, monkeypatch, mutation
):
    manifest, index, reader = cohort
    manifest = copy.deepcopy(manifest)
    refs = manifest["original_filing_outcome_refs"]
    if mutation == "duplicate":
        refs.append(refs[0])
    if mutation == "omitted":
        refs.pop()
    if mutation in ("substitution", "envelope", "execution"):
        record = reader.document(refs[0])
        if mutation == "substitution":
            record["inputs"]["target"]["cik"] = "0000009999"
        if mutation == "envelope":
            record["input_digest"] = "0" * 64
        if mutation == "execution":
            record["inputs"]["pins"]["source_commit"] = "f" * 40
    if mutation == "future":
        manifest["original_inventory"]["targets"][0]["accepted_at"] = (
            "2020-01-01T00:00:00Z"
        )
    if mutation == "label":
        manifest["issuer_decisions"][0]["label_accession"] = "0000009999-17-000001"
    monkeypatch.setattr(batch, "MANIFEST_DIGEST", sha256_digest(manifest))
    index = index.model_copy(update={"fixed_manifest_digest": batch.MANIFEST_DIGEST})
    with pytest.raises(batch.DesignError):
        batch.prepare_batch(manifest, index, tmp_path, reader, exact_commit="a" * 40)
    assert list(tmp_path.iterdir()) == []


def test_interrupted_publication_resumes_without_rewriting_prefix(cohort, tmp_path):
    manifest, index, reader = cohort
    output, artifacts = batch.prepare_batch(
        manifest, index, tmp_path, reader, exact_commit="a" * 40
    )
    subset = list(sorted(artifacts.items()))[:3]
    for _, raw in subset:
        batch.publish_report(tmp_path, json.loads(raw))
    before = {
        p: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
        for p in tmp_path.glob("*.json")
    }
    receipts = [
        batch.publish_report(tmp_path, json.loads(raw))
        for _, raw in sorted(artifacts.items())
    ]
    assert sum(row["wrote"] for row in receipts) == len(artifacts) - len(subset)
    assert all(
        (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes()) == state
        for p, state in before.items()
    )
    assert all(
        not batch.publish_report(tmp_path, json.loads(raw))["wrote"]
        for raw in artifacts.values()
    )
    assert output["complete_exact_study_cases"] == 0


def test_strict_index_accepts_json_arrays_without_python_tuple_coercion(cohort):
    _, index, _ = cohort
    assert batch.BatchIndex.model_validate_json(canonical_bytes(index)) == index
    with pytest.raises(batch.DesignError):
        checked_document(b'{"x":1,"x":2}', batch.digest(b'{"x":1,"x":2}'))


def retained_record():
    claim = evaluate()
    source, report = claim.source, claim.report
    target = {
        "cik": source.cik,
        "issuer_id": f"CIK:{source.cik}",
        "accession": source.accession_number,
        "form": source.form,
        "accepted_at": source.available_at.isoformat(),
        "valuation_timestamp": claim.decision_at.isoformat(),
        "period_end": claim.report_period_end.isoformat(),
        "role": "decision",
    }
    parser = report.model_dump(mode="json", exclude={"filing_path", "parsed_at"})
    inputs = {"target": target, "pins": {"source_commit": batch.PARSER_EXECUTION}}
    output = {
        "status": "validation_passed_unpublished",
        "canonical_release_published": False,
        "canonical_snapshot_published": False,
        "parser_report": parser,
        "parser_digest": report.replay_digest(),
        "sources": [
            {
                "uri": source.uri,
                "accession": source.accession_number,
                "available_at": target["accepted_at"],
                "form": source.form,
                "content_hash": source.content_hash,
            }
        ],
        "integrity_evidence": {
            "primary_document_uri": source.uri,
            "accession_number": source.accession_number,
            "raw_content_hash": source.content_hash,
            "parser_input_hash": source.parser_input_hash,
            "captured_at": source.captured_at.isoformat(),
        },
    }
    return target, {
        "inputs": inputs,
        "output": output,
        "input_digest": sha256_digest(inputs),
        "output_digest": sha256_digest(output),
    }


def test_archived_typed_report_uses_retained_capture_and_preserves_missing_receipt():
    target, record = retained_record()
    claim = batch.original_from_record(record, target)
    assert claim == evaluate()
    assert claim.source.http_status is None
    assert "regulatory_approval" in claim.unestablished_claims
    assert "mapping_review" in claim.unestablished_claims


@pytest.mark.parametrize(
    "mutation", ["parser_digest", "accession", "availability", "hash", "ambiguous"]
)
def test_archived_parser_and_source_metadata_must_match(mutation):
    target, record = retained_record()
    output = record["output"]
    if mutation == "parser_digest":
        output["parser_digest"] = "0" * 64
    if mutation == "accession":
        output["sources"][0]["accession"] = "0000000002-26-000001"
    if mutation == "availability":
        output["sources"][0]["available_at"] = "2026-02-02T00:00:00Z"
    if mutation == "hash":
        output["sources"][0]["content_hash"] = "0" * 64
    if mutation == "ambiguous":
        output["sources"].append(output["sources"][0])
    record["output_digest"] = sha256_digest(output)
    with pytest.raises(batch.DesignError):
        batch.original_from_record(record, target)
