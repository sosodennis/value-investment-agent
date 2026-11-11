from datetime import UTC, date, datetime, timedelta

import pytest
from fundamental_service.arelle_parser import (
    ArelleParserError,
    ArelleValidationProfileV1,
)
from fundamental_service.history_mapping_audit import DEFAULT_COHORT_MANIFEST, ROOT
from fundamental_service.history_original_validation import (
    OriginalValidationTargetV1,
    capture_scope,
    original_inventory,
    retained_original_result,
    validate_original,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import CapturedSource, SnapshotError
from fundamental_service.contracts import SourceRole


def target():
    return OriginalValidationTargetV1(
        issuer_id="CIK:0001539778",
        cik="0001539778",
        accession="0001477932-16-007985",
        form="10-K",
        period_end=date(2015, 9, 30),
        accepted_at=datetime(2016, 1, 12, tzinfo=UTC),
        valuation_timestamp=datetime(2016, 1, 12, tzinfo=UTC),
        role="decision",
    )


def test_fixed_inventory_retains_every_issuer_amendment_and_first_original_label():
    inventory = original_inventory(ROOT, DEFAULT_COHORT_MANIFEST)
    targets = inventory["targets"]
    issuers = inventory["issuers"]
    assert len(issuers) == 100 and len(targets) == 589
    assert sum(t.form == "10-K/A" for t in targets) == 48
    assert sum(t.role == "decision" for t in targets) == 100
    assert sum(t.role == "label" for t in targets) == 91
    assert sum(i["label_missing_reason"] is not None for i in issuers) == 9
    for issuer in issuers:
        selected = [t for t in targets if t.issuer_id == issuer["issuer_id"]]
        labels = [t for t in selected if t.role == "label"]
        assert [t.accession for t in labels] == (
            [issuer["label_accession"]] if issuer["label_accession"] else []
        )
        assert all(t.accepted_at <= t.valuation_timestamp for t in selected)
    assert canonical_bytes(inventory) == canonical_bytes(
        original_inventory(ROOT, DEFAULT_COHORT_MANIFEST)
    )


def test_replaced_cohort_fails_before_sources(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="cannot replace"):
        original_inventory(tmp_path, manifest)


def test_inventory_uses_explicit_root_without_repository_layout(tmp_path):
    import json
    import shutil

    manifest = tmp_path / DEFAULT_COHORT_MANIFEST.relative_to(ROOT)
    manifest.parent.mkdir(parents=True)
    files = [
        DEFAULT_COHORT_MANIFEST.relative_to(ROOT),
        "docs/acceptance/issue-359-cohort-protocol-v1.json",
        "docs/acceptance/issue-359-sec-cohort-v1/frame_manifest.json",
    ]
    cohort = json.loads(DEFAULT_COHORT_MANIFEST.read_bytes())
    frame = json.loads((ROOT / files[-1]).read_bytes())
    files.extend(row["snapshot_path"] for row in cohort["issuers"])
    files.extend(row["stored_snapshot"]["path"] for row in frame["sources"])
    for relative in files:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    expected = original_inventory(ROOT, DEFAULT_COHORT_MANIFEST)
    assert canonical_bytes(original_inventory(tmp_path, manifest)) == canonical_bytes(
        expected
    )
    (tmp_path / files[-1]).unlink()
    with pytest.raises(ValueError, match="missing"):
        original_inventory(tmp_path, manifest)


def test_future_and_amended_decision_targets_fail():
    fields = target().model_dump()
    fields["accepted_at"] += timedelta(seconds=1)
    with pytest.raises(ValueError, match="not available"):
        OriginalValidationTargetV1(**fields)
    fields = target().model_dump()
    fields["form"] = "10-K/A"
    with pytest.raises(ValueError, match="original annual"):
        OriginalValidationTargetV1(**fields)


@pytest.mark.parametrize("status", ["validation_passed_unpublished", "refused"])
def test_repeat_reuses_success_or_failure_without_evaluation_or_new_files(
    tmp_path, status
):
    artifacts = ArtifactStore(tmp_path)
    inputs = {"target": target(), "runtime": {"commit": "a" * 40}}
    output = {
        "status": status,
        "code": "PARSER_VALIDATION_BLOCKED" if status == "refused" else None,
    }
    first, wrote = retained_original_result(
        inputs, artifacts=artifacts, evaluate=lambda: output
    )
    assert wrote
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }

    def forbidden():
        raise AssertionError("a repeat cannot fetch, parse or publish")

    second, wrote = retained_original_result(
        inputs, artifacts=artifacts, evaluate=forbidden
    )
    after = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert not wrote and before == after
    assert canonical_bytes(first) == canonical_bytes(second)


def test_programming_error_is_not_a_retained_financial_failure(tmp_path):
    artifacts = ArtifactStore(tmp_path)

    def error():
        raise TypeError("programming defect")

    with pytest.raises(TypeError, match="programming defect"):
        retained_original_result(
            {"target": target()}, artifacts=artifacts, evaluate=error
        )
    with pytest.raises(SnapshotError, match="artifact"):
        artifacts.get(
            "history-original-validation:" + sha256_digest({"target": target()})
        )


@pytest.mark.parametrize(
    "failure",
    [
        SnapshotError("PARSER_VALIDATION_BLOCKED", "blocked"),
        ArelleParserError("DQC_TAXONOMY_UNSUPPORTED", "unsupported"),
    ],
)
def test_original_refusals_keep_target_sources_and_never_publish(tmp_path, failure):
    import json

    t = target()
    index = json.dumps(
        {
            "directory": {
                "item": [
                    {"name": "original.xml", "size": "1"},
                    {"name": "original.xsd", "size": "1"},
                    {"name": t.accession + "-xbrl.zip", "size": "1"},
                ]
            }
        }
    ).encode()

    class Adapter:
        def capture_filing_index(self, **kwargs):
            return CapturedSource(
                "sec-filing-index",
                "https://www.sec.gov/index.json",
                SourceRole.REFERENCE,
                index,
                "application/json",
                200,
                t.accepted_at,
            )

        def capture_filing(self, **kwargs):
            return CapturedSource(
                "sec-filing",
                "https://www.sec.gov/original.xml",
                SourceRole.FILING,
                b"<xbrl/>",
                "application/xml",
                200,
                t.accepted_at,
            )

        def capture_filing_archive(self, **kwargs):
            return self.capture_filing(**kwargs)

    class Ingestion:
        def prepare_filing(self, **kwargs):
            assert kwargs["mappings"] == ()
            assert kwargs["valuation_timestamp"] == t.valuation_timestamp
            assert kwargs["identity"].security_id.startswith("diagnostic:")
            raise failure

    result = validate_original(
        t,
        service=Ingestion(),
        adapter=Adapter(),
        profile=ArelleValidationProfileV1(profile_id="fixture"),
        cache=tmp_path,
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert result["status"] == "refused" and result["code"] == failure.code
    assert len(result["sources"]) == 3
    assert (
        not result["canonical_snapshot_published"]
        and not result["canonical_release_published"]
    )
    scope = capture_scope(t)
    assert scope.cik == t.cik and scope.accession_number == t.accession
    assert scope.valuation_timestamp == t.valuation_timestamp
