"""Source receipt recovery cannot manufacture parser or accounting authority."""

from __future__ import annotations

import copy
import io
import json
import sys
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import pytest

from fundamental_service.arelle_parser import (
    ArelleValidationProfileV1,
    fact_semantic_digest,
)
from fundamental_service.historical_dqc import V3_PROFILE
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    _SecResponse,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import CapturedSource, SnapshotError
from test_original_issuer import ACCEPTED, CAPTURED, DECISION, original

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import recover_history_originals as recovery  # noqa: E402
import read_retained_history_corpus as corpus  # noqa: E402


def frame(inputs, output):
    return {
        "inputs": inputs,
        "input_digest": sha256_digest(inputs),
        "output": output,
        "output_digest": sha256_digest(output),
    }


@pytest.fixture
def example():
    report, source = original()
    resources = {
        "EDGAR": "a" * 64,
        "xule": "b" * 64,
        "modern-dqc.zip": "c" * 64,
        "historical-v3": V3_PROFILE.source_sha256,
    }
    profile = ArelleValidationProfileV1(
        profile_id=V3_PROFILE.profile_id,
        dqc_version=V3_PROFILE.dqc_version,
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path("EDGAR"),
        xule_plugin_dir=Path("xule"),
        dqc_ruleset_path=Path("modern-dqc.zip"),
        historical_dqc_dir=Path("historical-v3"),
        edgar_plugin_sha256=resources["EDGAR"],
        xule_plugin_sha256=resources["xule"],
        dqc_ruleset_sha256=resources["modern-dqc.zip"],
        historical_dqc_sha256=resources["historical-v3"],
    )
    pins = {
        "profile_digest": profile.digest(),
        "resource_pins": resources,
        "runtime": {"arelle": "2.47.4"},
        "taxonomy_cache_pin": "d" * 64,
    }
    primary, schema = b"<xbrl>retained input</xbrl>", b"<schema/>"
    stream = io.BytesIO()
    with ZipFile(stream, "w") as zipped:
        zipped.writestr("original.xml", primary)
        zipped.writestr("original.xsd", schema)
    archive = stream.getvalue()
    archive_uri = source.uri.rsplit("/", 1)[0] + f"/{source.accession_number}-xbrl.zip"
    target = {
        "issuer_id": f"CIK:{source.cik}",
        "cik": source.cik,
        "accession": source.accession_number,
        "accepted_at": "2026-02-01T00:00:00Z",
        "valuation_timestamp": "2026-03-01T00:00:00Z",
        "period_end": "2025-12-31",
        "role": "decision",
        "form": "10-K",
    }

    def descriptor(uri, raw):
        return {
            "uri": uri,
            "available_at": target["accepted_at"],
            "content_hash": recovery.digest(raw),
            "byte_length": len(raw),
            "http_status": None,
        }

    selection = {
        **{
            k: target[k]
            for k in ("cik", "accession", "accepted_at", "valuation_timestamp")
        },
        "primary_document": "original.xml",
        "archive": descriptor(archive_uri, archive),
        "index": descriptor(source.uri.rsplit("/", 1)[0] + "/index.json", b"{}"),
        "direct": descriptor(source.uri, b"different direct input"),
        "members": [
            {
                "filename": name,
                "content_hash": recovery.digest(raw),
                "byte_length": len(raw),
            }
            for name, raw in (("original.xml", primary), ("original.xsd", schema))
        ],
        "policy_digest": corpus.SELECTION_POLICY_DIGEST,
        "policy_id": "sec-original-xbrl-archive-v1",
        "semantic_equivalence": "not_assessed",
        "canonical_publication_approved": False,
        "discrepancies": [
            "DIRECT_ARCHIVE_BYTES_DIFFER",
            "CAPTURE_HTTP_RECEIPTS_UNAVAILABLE",
        ],
    }
    report = report.model_copy(
        update={
            "validation_profile": profile,
            "validation_profile_digest": profile.digest(),
            "source_content_hash": recovery.digest(primary),
            "taxonomy_cache_hash": pins["taxonomy_cache_pin"],
        }
    )
    output = {
        "status": "parsed_without_blockers",
        "canonical_publication_approved": False,
        "fact_count": len(report.facts),
        "facts": [f.model_dump(mode="json") for f in report.facts],
        "findings": [],
        "blocking_codes": [],
        "network_attempt_count": 0,
        "report_replay_digest": report.replay_digest(),
        "fact_semantic_digest": fact_semantic_digest(report),
        "taxonomy_version": report.taxonomy_version,
        "validation_engines": [],
        "validation_evidence": [],
    }
    selected = {
        "target": target,
        "selection": selection,
        "selection_digest": sha256_digest(selection),
        "selection_status": "selected_for_validation",
        "publication_approved": False,
        "original_result_digest": "e" * 64,
        "original_source_comparison": {"relation": "canonical_xml_different"},
    }
    parser_row = {
        "target": target,
        "status": output["status"],
        "canonical_publication_approved": False,
        "report_digest": "f" * 64,
        "blocking_codes": [],
    }
    row = corpus.CorpusRow(selected, parser_row, output)
    captured = CapturedSource(
        source_id="sec-filing-archive",
        uri=archive_uri,
        role=source.role,
        content=archive,
        media_type="application/zip",
        http_status=200,
        available_at=ACCEPTED,
        captured_at=CAPTURED,
        accession_number=source.accession_number,
        form="10-K",
    )
    return row, pins, captured


class Provider(SecEdgarSourceAdapter):
    def __init__(self, captured, error=None):
        super().__init__(SecRequestPolicy(user_agent="test test@example.com"))
        self.captured, self.error, self.calls = captured, error, 0

    def _request(self, uri, *, deadline_at=None):
        self.calls += 1
        if self.error:
            raise self.error
        assert uri == self.captured.uri
        return _SecResponse(
            content=self.captured.content,
            http_status=self.captured.http_status,
            media_type=self.captured.media_type,
            available_at=self.captured.captured_at,
            response_headers=(("etag", "retained"),),
            declared_size=len(self.captured.content),
        )


def inventory(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_real_zip_receipt_and_exact_member_keep_distinct_provenance(example):
    row, pins, captured = example
    result = recovery.original_from_capture(row, pins, captured)
    assert result.status == "matched"
    assert result.source.uri.endswith("-xbrl.zip")
    assert result.source.captured_at == CAPTURED
    assert result.source.http_status == 200
    assert result.source.content_hash == recovery.digest(captured.content)
    assert (
        result.source.parser_input_hash == row.selection["members"][0]["content_hash"]
    )
    assert result.report.parsed_at == CAPTURED
    assert result.report.replay_digest() == row.parser_output["report_replay_digest"]
    assert "mapping_review" in result.unestablished_claims
    assert "regulatory_approval" in result.unestablished_claims


@pytest.mark.parametrize(
    "field,value",
    [
        ("uri", "https://invalid.invalid/other.zip"),
        ("http_status", 403),
        ("content", b"different"),
        ("captured_at", None),
        ("accession_number", "0000000001-26-000002"),
        ("is_amendment", True),
        ("available_at", DECISION),
    ],
)
def test_changed_or_missing_capture_evidence_is_refused(example, field, value):
    row, pins, captured = example
    with pytest.raises(SnapshotError, match="actual ZIP receipt"):
        recovery.original_from_capture(row, pins, replace(captured, **{field: value}))


@pytest.mark.parametrize(
    "mutation", ["member_hash", "member_length", "primary", "duplicate", "escape"]
)
def test_member_or_selection_substitution_fails(example, mutation):
    row, pins, captured = copy.deepcopy(example)
    selection = row.selection
    if mutation == "member_hash":
        selection["members"][0]["content_hash"] = "0" * 64
    elif mutation == "member_length":
        selection["members"][0]["byte_length"] += 1
    elif mutation == "primary":
        selection["primary_document"] = "absent.xml"
    elif mutation == "duplicate":
        selection["members"].append(selection["members"][0])
    else:
        selection["members"][0]["filename"] = "../escape.xml"
    with pytest.raises((SnapshotError, recovery.DesignError)):
        recovery.original_from_capture(row, pins, captured)


@pytest.mark.parametrize(
    "mutation",
    ["facts", "replay", "semantic", "count", "network", "blockers", "profile", "cache"],
)
def test_retained_parser_cannot_be_relabelled_or_mutated(example, mutation):
    row, pins, _ = copy.deepcopy(example)
    output = row.parser_output
    if mutation == "facts":
        output["facts"][-1]["value"] = "999"
    elif mutation in ("replay", "semantic"):
        output[
            "report_replay_digest" if mutation == "replay" else "fact_semantic_digest"
        ] = "0" * 64
    elif mutation == "count":
        output["fact_count"] += 1
    elif mutation == "network":
        output["network_attempt_count"] = 1
    elif mutation == "blockers":
        output["blocking_codes"] = ["DQC.blocker"]
    elif mutation == "profile":
        pins["profile_digest"] = "0" * 64
    else:
        pins["taxonomy_cache_pin"] = "0" * 64
    with pytest.raises(recovery.DesignError):
        corpus.retained_report(output, row.selection, pins, normalization_at=CAPTURED)


def test_actual_capture_then_network_disabled_repeat_writes_nothing(example, tmp_path):
    row, pins, captured = example
    provider = Provider(captured)
    first, refs, wrote = recovery.recover_corpus([row], pins, provider, tmp_path)
    assert wrote and len(refs) == 1 and provider.calls == 1
    before = inventory(tmp_path)
    second, refs2, wrote2 = recovery.recover_corpus(
        [row], pins, recovery.OfflineSource(provider.policy), tmp_path
    )
    assert not wrote2 and refs2 == refs
    assert canonical_bytes(first) == canonical_bytes(second)
    assert inventory(tmp_path) == before


def test_source_failure_is_cached_and_not_retried(example, tmp_path):
    row, pins, captured = example
    provider = Provider(
        captured, SnapshotError("SEC_RATE_LIMITED", "provider failure", retryable=True)
    )
    first, refs, wrote = recovery.recover_corpus([row], pins, provider, tmp_path)
    assert wrote and not refs and provider.calls == 1
    before = inventory(tmp_path)
    second, refs2, wrote2 = recovery.recover_corpus(
        [row], pins, recovery.OfflineSource(provider.policy), tmp_path
    )
    assert not wrote2 and not refs2 and second == first
    assert inventory(tmp_path) == before
    assert first["rows"][0]["failure_code"] == "SEC_RATE_LIMITED"


def test_invalidated_failure_attempt_cannot_be_reused(example, tmp_path):
    row, pins, captured = example
    provider = Provider(captured, SnapshotError("SEC_RATE_LIMITED", "provider refusal"))
    recovery.recover_corpus([row], pins, provider, tmp_path)
    recovery.ArtifactStore(tmp_path / "receipts").invalidate(
        "history-original-recovery:" + sha256_digest(row.identity())
    )
    before = inventory(tmp_path)
    with pytest.raises(SnapshotError) as error:
        recovery.recover_corpus([row], pins, provider, tmp_path)
    assert error.value.code == "RECOVERY_ATTEMPT_INVALID"
    assert provider.calls == 1 and inventory(tmp_path) == before


def test_offline_cache_miss_does_not_poison_future_network_attempt(example, tmp_path):
    row, pins, captured = example
    provider = Provider(captured)
    with pytest.raises(SnapshotError) as error:
        recovery.recover_corpus(
            [row], pins, recovery.OfflineSource(provider.policy), tmp_path
        )
    assert error.value.code == "NETWORK_DISABLED"
    _, refs, _ = recovery.recover_corpus([row], pins, provider, tmp_path)
    assert len(refs) == 1 and provider.calls == 1


@pytest.mark.parametrize("after_attempt", [False, True])
def test_interruption_after_capture_or_attempt_reuses_source(
    example, tmp_path, monkeypatch, after_attempt
):
    row, pins, captured = example
    provider = Provider(captured)
    if after_attempt:
        original_function = recovery.publish_report
        monkeypatch.setattr(
            recovery,
            "publish_report",
            lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
    else:
        original_function = recovery.original_from_capture
        monkeypatch.setattr(
            recovery,
            "original_from_capture",
            lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
    with pytest.raises(KeyboardInterrupt):
        recovery.recover_corpus([row], pins, provider, tmp_path)
    monkeypatch.setattr(
        recovery,
        "publish_report" if after_attempt else "original_from_capture",
        original_function,
    )
    _, refs, wrote = recovery.recover_corpus(
        [row], pins, recovery.OfflineSource(provider.policy), tmp_path
    )
    assert wrote and len(refs) == 1 and provider.calls == 1


def test_corrupt_retained_bytes_fail_without_download(example, tmp_path):
    row, pins, captured = example
    provider = Provider(captured)
    recovery.recover_corpus([row], pins, provider, tmp_path)
    blob = next((tmp_path / "content").rglob("*.bin"))
    blob.write_bytes(b"changed")
    with pytest.raises(SnapshotError) as error:
        recovery.recover_corpus([row], pins, provider, tmp_path)
    assert error.value.code == "SOURCE_HASH_MISMATCH"
    assert provider.calls == 1


def test_blockers_and_failures_are_retained_without_provider_io(example, tmp_path):
    row, pins, captured = example
    rows = []
    for status in ("parsed_with_blockers", "parser_refused", "selection_refused"):
        parser_row = {
            **row.parser_row,
            "status": status,
            "failure_code": "ORIGINAL_FAILURE",
            "blocking_codes": ["DQC.original"],
        }
        rows.append(replace(row, parser_row=parser_row))
    provider = Provider(captured)
    output, refs, wrote = recovery.recover_corpus(rows, pins, provider, tmp_path)
    assert provider.calls == 0 and not refs and not wrote
    assert output["filing_count"] == 3 and output["recovery_eligible_count"] == 0
    assert all(
        r["prior_failure_code"] == "ORIGINAL_FAILURE"
        and r["prior_blocking_codes"] == ["DQC.original"]
        for r in output["rows"]
    )
    assert output["supported_history_threshold"] is None


@pytest.fixture
def corpus_files(example, tmp_path, monkeypatch):
    row, pins, _ = copy.deepcopy(example)
    pins["selection_report_digest"] = "temporary"
    selection_output = {"rows": [row.selection_row]}
    selection_raw = canonical_bytes(frame({"protocol": "selection"}, selection_output))
    monkeypatch.setattr(corpus, "CORPUS_SIZE", 1)
    monkeypatch.setattr(corpus, "SELECTION_DIGEST", recovery.digest(selection_raw))
    pins["selection_report_digest"] = recovery.digest(selection_raw)
    result = frame(
        {
            "protocol_input_digest": sha256_digest(pins),
            "selection_digest": row.selection_row["selection_digest"],
            "target": row.target,
        },
        row.parser_output,
    )
    result_raw = canonical_bytes(result)
    result_digest = recovery.digest(result_raw)
    (tmp_path / f"{result_digest}.json").write_bytes(result_raw)
    parser_row = {
        **row.parser_row,
        "report_digest": result_digest,
        "input_digest": result["input_digest"],
        "output_digest": result["output_digest"],
    }
    parser_raw = canonical_bytes(frame(pins, {"rows": [parser_row]}))
    monkeypatch.setattr(corpus, "PARSER_DIGEST", recovery.digest(parser_raw))
    manifest = {
        "original_filing_outcome_refs": [
            {"sha256": row.selection_row["original_result_digest"]}
        ]
    }
    monkeypatch.setattr(
        corpus,
        "fixed_targets",
        lambda _: ([], {corpus.target_key(row.target): row.target}),
    )
    monkeypatch.setattr(corpus, "original_from_record", lambda record, target: None)

    class Reader:
        def document(self, ref):
            return {"output": {"code": "SOURCE_ARCHIVE_SIZE_MISMATCH"}}

    return manifest, selection_raw, parser_raw, Reader(), tmp_path


def test_complete_corpus_checks_all_results_before_recovery(corpus_files):
    manifest, selection, parser, reader, results = corpus_files
    _, rows = corpus.load_corpus(manifest, selection, parser, results, reader)
    assert len(rows) == 1 and rows[0].parser_row["status"] == "parsed_without_blockers"


@pytest.mark.parametrize(
    "mutation",
    [
        "selection_digest",
        "parser_digest",
        "result_bytes",
        "missing_result",
        "duplicate",
        "original_ref",
        "target",
    ],
)
def test_incomplete_or_substituted_corpus_fails_before_provider_io(
    corpus_files, monkeypatch, mutation
):
    manifest, selection, parser, reader, results = copy.deepcopy(corpus_files)
    if mutation == "selection_digest":
        selection += b" "
    elif mutation == "parser_digest":
        parser += b" "
    elif mutation in ("result_bytes", "missing_result"):
        path = next(results.glob("*.json"))
        if mutation == "result_bytes":
            path.write_bytes(b"{}")
        else:
            path.unlink()
    elif mutation == "original_ref":
        manifest["original_filing_outcome_refs"] = []
    else:
        doc = json.loads(parser)
        if mutation == "duplicate":
            doc["output"]["rows"].append(doc["output"]["rows"][0])
        else:
            doc["output"]["rows"][0]["target"]["cik"] = "0000000002"
        parser = canonical_bytes(frame(doc["inputs"], doc["output"]))
        monkeypatch.setattr(corpus, "PARSER_DIGEST", recovery.digest(parser))
    with pytest.raises((recovery.DesignError, OSError)):
        corpus.load_corpus(manifest, selection, parser, results, reader)


@pytest.mark.parametrize(
    "mutation",
    [
        "future",
        "uri",
        "amendment",
        "policy",
        "equivalence",
        "approval",
        "duplicate",
        "escape",
    ],
)
def test_selection_boundaries_preserve_original_authority(example, mutation):
    row, _, _ = copy.deepcopy(example)
    target, selected = row.target, row.selection
    if mutation == "future":
        selected["accepted_at"] = "2027-01-01T00:00:00Z"
    elif mutation == "uri":
        selected["archive"]["uri"] += "different"
    elif mutation == "amendment":
        target["form"] = "10-K/A"
    elif mutation == "policy":
        selected["policy_digest"] = "0" * 64
    elif mutation == "equivalence":
        selected["semantic_equivalence"] = "approved"
    elif mutation == "approval":
        selected["canonical_publication_approved"] = True
    elif mutation == "duplicate":
        selected["members"].append(selected["members"][0])
    else:
        selected["members"][0]["filename"] = "../escape"
    with pytest.raises(recovery.DesignError):
        corpus.check_selection(selected, target)


def test_two_concurrent_recoveries_share_one_actual_source_request(example, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    row, pins, captured = example
    provider = Provider(captured)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: recovery.recover_corpus([row], pins, provider, tmp_path),
                range(2),
            )
        )
    assert provider.calls == 1
    assert results[0][0] == results[1][0]
    assert sum(result[2] for result in results) == 1


def test_supplement_preserves_existing_original_and_rejects_replacement(
    example, tmp_path
):
    from datetime import timedelta

    row, pins, captured = example
    original = recovery.original_from_capture(row, pins, captured)
    published = recovery.publish_report(tmp_path, json.loads(canonical_bytes(original)))
    reference = recovery.FileReference(
        path=f"{published['report_digest']}.json", sha256=sha256_digest(original)
    )
    base = recovery.BatchIndex(
        schema_version="history-study-batch-index.v1",
        fixed_manifest_digest=recovery.MANIFEST_DIGEST,
        runtime=recovery.runtime_pins(),
        originals=(reference,),
    )
    target = {corpus.target_key(row.target): row.target}
    absolute = recovery.FileReference(
        path=str(tmp_path / reference.path), sha256=reference.sha256
    )
    unchanged = recovery.supplement_index(base, tmp_path, [absolute], target)
    assert unchanged.originals == (absolute,)
    assert unchanged.runtime == base.runtime and unchanged.seeds == base.seeds
    alternate = recovery.original_from_capture(
        row,
        pins,
        replace(captured, captured_at=captured.captured_at + timedelta(seconds=1)),
    )
    receipt = recovery.publish_report(tmp_path, json.loads(canonical_bytes(alternate)))
    replacement = recovery.FileReference(
        path=str(tmp_path / f"{receipt['report_digest']}.json"),
        sha256=sha256_digest(alternate),
    )
    with pytest.raises(recovery.DesignError, match="cannot replace"):
        recovery.supplement_index(base, tmp_path, [replacement], target)
