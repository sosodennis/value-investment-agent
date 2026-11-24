import json
import shutil
import sys
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from fundamental_service.contracts import SourceRole
from fundamental_service.free_source_policy import free_market_source_policy
from fundamental_service.public_acquisition import (
    PublicSourceAcquisition,
    PublicSourceAcquisitionRequestV1,
)
from fundamental_service.public_source import PublicSourceAdapter
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import (
    CapturedSource,
    FilesystemContentStore,
    SnapshotError,
)
from fundamental_service.source_admission import TermsRequirementV1
from fundamental_service.public_source_catalog import (
    default_public_source_registrations,
)
from treasury_source_fixtures import TREASURY_XML

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import reproduce_source_coverage as coverage  # noqa: E402

AT = datetime(2026, 11, 24, 12, tzinfo=UTC)
TEST_TERMS = b"<html><body>Synthetic test-only government works notice.</body></html>"


def forbidden(*args, **kwargs):
    raise AssertionError("replay attempted parser or HTTP I/O")


def inventory(root):
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture(scope="module")
def cohort():
    return coverage.Cohort.model_validate_json(coverage.DEFAULT_COHORT.read_bytes())


@pytest.fixture(scope="module")
def sec_evidence(tmp_path_factory, cohort):
    root = tmp_path_factory.mktemp("real-sec-coverage")
    result = coverage.reproduce_sec(cohort, root)
    return root, result


def test_real_frozen_originals_preserve_periods_and_partial_results(
    cohort, sec_evidence
):
    _, observations = sec_evidence
    apple, tesla, amendment = observations
    assert apple["case_id"] == "aapl-fy2024-original"
    assert apple["parsing"] == "parsed"
    assert apple["fact_count"] > 1000
    assert {item["inclusive_days"] for item in apple["duration_contexts"]} >= {364, 371}
    assert apple["custom_qnames"]
    assert apple["missing_observation_roles"] == ()
    assert tesla["parsing"] == "partial"
    assert "operating_cash_flow" in tesla["missing_observation_roles"]
    assert amendment["parsing"] == "unsupported"
    assert amendment["observations"]["operating_cash_flow"] == ()
    assert amendment["amendment_scope"] == "unknown"
    assert amendment["amends_accession"] == "0001628280-25-003063"
    for result in observations:
        assert result["calculation_qualification"] == "SEC_VALIDATION_REQUIRED"
        assert result["semantic_comparability"] == "not_established"
    assert cohort.supported_history_threshold is None


def test_real_sec_replay_rechecks_reports_without_parser_or_file_changes(
    monkeypatch, cohort, sec_evidence
):
    root, original = sec_evidence
    before = inventory(root)
    monkeypatch.setattr(coverage, "parse_filing_offline", forbidden)
    assert coverage.reproduce_sec(cohort, root) == original
    assert inventory(root) == before


def test_replay_refuses_corrupt_report_without_reparsing(
    tmp_path, monkeypatch, cohort, sec_evidence
):
    source, _ = sec_evidence
    root = tmp_path / "corrupt"
    shutil.copytree(source, root)
    store = ArtifactStore(root / "artifacts")
    record = store.get("source-coverage-parser:aapl-fy2024-original")
    next((root / "artifacts").glob(record.content_hash + ".*.artifact")).write_bytes(
        b"{}"
    )
    monkeypatch.setattr(coverage, "parse_filing_offline", forbidden)
    with pytest.raises(SnapshotError) as error:
        coverage.reproduce_sec(cohort, root)
    assert error.value.code == "ARTIFACT_HASH_MISMATCH"


@pytest.mark.parametrize("drift", ["profile", "runtime", "dependency"])
def test_replay_refuses_changed_parser_identity(
    tmp_path, monkeypatch, cohort, sec_evidence, drift
):
    source, _ = sec_evidence
    root = tmp_path / "drift"
    shutil.copytree(source, root)
    monkeypatch.setattr(coverage, "parse_filing_offline", forbidden)
    if drift == "profile":
        monkeypatch.setattr(
            coverage,
            "PROFILE",
            coverage.PROFILE.model_copy(update={"profile_id": "changed-profile"}),
        )
    elif drift == "runtime":
        monkeypatch.setattr(coverage, "version", lambda _: "0.0.0")
    else:
        log = root / "artifacts/.artifact-records.jsonl"
        records = [json.loads(line) for line in log.read_text().splitlines()]
        records[0]["dependency_hashes"] = ["0" * 64]
        log.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    with pytest.raises(ValueError, match="dependencies changed"):
        coverage.reproduce_sec(cohort, root)


def test_source_change_is_refused_before_parser(tmp_path, monkeypatch, cohort):
    case = cohort.cases[0]
    original = coverage.CaptureManifest.model_validate_json(
        (coverage.REPOSITORY / cohort.source_manifest).read_bytes()
    )
    entry = next(item for item in original.sources if item.path == case.filing_path)
    (tmp_path / entry.path).write_bytes(b"changed retained original")
    monkeypatch.setattr(coverage, "parse_filing_offline", forbidden)
    with pytest.raises(ValueError, match="source integrity failed"):
        coverage.verified_source(case, entry, tmp_path, filing=True)


def test_archive_escape_is_refused(tmp_path):
    from zipfile import ZipFile

    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("../escape.xsd", b"not safe")
    with pytest.raises(ValueError, match="unsafe archive"):
        coverage.extract_resources(archive, tmp_path / "output")
    assert not (tmp_path / "escape.xsd").exists()


@pytest.fixture
def public_evidence(tmp_path, monkeypatch, cohort):
    case = cohort.public_source_case
    adapter = PublicSourceAdapter(user_agent="Test <test@example.invalid>")
    specs = {
        item.spec.source_id: item.spec for item in default_public_source_registrations()
    }
    requests = tuple(
        PublicSourceAcquisitionRequestV1(
            source_id=source_id,
            uri=uri,
            source_profile=profile,
            terms_reference=specs[source_id].terms_reference,
            valuation_timestamp=AT - timedelta(minutes=1),
        )
        for source_id, uri, profile in (
            (case.source_id, case.source_uri, case.source_profile),
            (
                case.terms_source_id,
                "https://www.govinfo.gov/content/pkg/USCODE-2024-title17/html/USCODE-2024-title17-chap1-sec105.htm",
                "us-government-works-terms-html-v1",
            ),
        )
    )
    (tmp_path / "requests.json").write_bytes(canonical_bytes(requests))

    class SyntheticProvider:
        def validate_capture(self, source_id, uri):
            return adapter.validate_capture(source_id, uri)

        def capture(self, source_id, uri):
            is_data = source_id == case.source_id
            return CapturedSource(
                source_id=source_id,
                uri=uri,
                role=SourceRole.MACRO if is_data else SourceRole.REFERENCE,
                content=TREASURY_XML.replace(b"2025-03-28", b"2026-03-28")
                if is_data
                else TEST_TERMS,
                media_type="application/xml" if is_data else "text/html",
                http_status=200,
                captured_at=AT,
                available_at=AT,
            )

    owner = PublicSourceAcquisition(
        provider=SyntheticProvider(),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        content=FilesystemContentStore(tmp_path / "content"),
        capture_lock=lambda _: nullcontext(),
    )
    for request in requests:
        owner.execute(request)
    policy = free_market_source_policy()
    rules = tuple(
        rule.model_copy(
            update={
                "terms": (
                    TermsRequirementV1(
                        uri=requests[1].uri,
                        content_sha256=sha256(TEST_TERMS).hexdigest(),
                    ),
                )
            }
        )
        if rule.provider_id == case.provider_id
        and rule.source_version == case.source_profile
        else rule
        for rule in policy.rules
    )
    monkeypatch.setattr(
        coverage,
        "load_runtime_source_use_policy",
        lambda: policy.model_copy(update={"rules": rules}),
    )
    monkeypatch.setattr(PublicSourceAdapter, "capture", forbidden)
    return tmp_path


def test_public_replay_uses_owner_refusals_and_preserves_all_evidence(
    public_evidence, cohort
):
    first = coverage.reproduce_public(cohort.public_source_case, public_evidence)
    cases = first["cases"]
    assert cases["normal_preparation"].admission.status == "admitted"
    expected = {
        "raw_data_redistribution": "SOURCE_USE_PURPOSE_UNSUPPORTED",
        "missing_terms": "SOURCE_USE_TERMS_MISSING",
        "wrong_policy_digest": "SOURCE_ADMISSION_POLICY_MISMATCH",
        "earlier_cutoff": "SOURCE_NOT_AVAILABLE_AT_VALUATION",
        "changed_terms_mutation_check": "SOURCE_USE_TERMS_CHANGED",
        "no_policy_rule_mutation_check": "SOURCE_USE_POLICY_MISSING",
    }
    for name, code in expected.items():
        assert code in cases[name].issue_codes
    assert first["valuation_at"] == AT
    assert all(
        item.issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
        for item in first["captures"]
    )
    before = inventory(public_evidence)
    second = coverage.reproduce_public(cohort.public_source_case, public_evidence)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert inventory(public_evidence) == before


def test_missing_public_capture_fails_without_network(public_evidence, cohort):
    (public_evidence / "artifacts/.artifact-records.jsonl").write_bytes(b"")
    with pytest.raises(SnapshotError) as error:
        coverage.reproduce_public(cohort.public_source_case, public_evidence)
    assert error.value.code == "ARTIFACT_NOT_FOUND"


def test_corrupt_public_original_is_refused_without_download(public_evidence, cohort):
    content = next(
        path for path in (public_evidence / "content").rglob("*") if path.is_file()
    )
    content.write_bytes(b"corrupt")
    with pytest.raises(SnapshotError):
        coverage.reproduce_public(cohort.public_source_case, public_evidence)


def test_output_cannot_overwrite_evidence(tmp_path):
    with pytest.raises(SystemExit) as result:
        coverage.main(
            ["--evidence-dir", str(tmp_path), "--output", str(tmp_path / "output.json")]
        )
    assert result.value.code == 2


def matrix_row(cohort, **changes):
    import verify_source_research_matrix as matrix

    case = cohort.public_source_case
    return matrix.ResearchRow(
        row_id="treasury",
        data_definition="Captured Treasury 10Y",
        owner="macro",
        source_ids=(case.source_id,),
        provider_id=case.provider_id,
        metric_ids=(case.metric_id,),
        source_profiles=(case.source_profile,),
        original_urls=(case.source_uri,),
        free_scope="Public source research",
        update_and_cost="Daily",
        time_and_coverage="Capture-time availability",
        rights=matrix.Rights(
            **{
                use: matrix.ResearchUse(
                    status="unconfirmed", reason="Research has not established this use"
                )
                for use in matrix.Rights.model_fields
            }
        ),
        evidence_refs=("test-terms",),
        downstream_impact="No financial policy approval",
    ).model_copy(update=changes)


def test_matrix_checks_registration_profile_and_terms_without_granting_admission(
    tmp_path, cohort, public_evidence
):
    import verify_source_research_matrix as matrix

    (tmp_path / "research-pages").mkdir(exist_ok=True)
    (tmp_path / "research-pages/terms.html").write_bytes(TEST_TERMS)
    evidence = matrix.ResearchEvidence(
        evidence_id="test-terms",
        uri="https://www.govinfo.gov/content/pkg/USCODE-2024-title17/html/USCODE-2024-title17-chap1-sec105.htm",
        checked_on=AT.date(),
        content_sha256=sha256(TEST_TERMS).hexdigest(),
        boundary="whole document",
        quote="Synthetic test-only government works notice.",
        status="captured",
        artifact_ref="research-pages/terms.html",
    )
    row = matrix_row(cohort)
    alfred = matrix_row(
        cohort,
        row_id="alfred-no-grant",
        source_ids=("alfred-vintage",),
        source_profiles=("alfred-dgs10-csv-vintage-v1",),
        provider_id="alfred",
    )
    manifest = matrix.Matrix(
        protocol="source-use-research-matrix-v1",
        checked_on=AT.date(),
        rows=(row, alfred),
        evidence=(evidence,),
    )
    path = tmp_path / "matrix.json"
    path.write_bytes(canonical_bytes(manifest))
    acquisitions = PublicSourceAcquisition(
        provider=PublicSourceAdapter(user_agent="Test <test@example.invalid>"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        content=FilesystemContentStore(tmp_path / "content"),
        capture_lock=lambda _: nullcontext(),
    )
    result = matrix.verify_matrix(path, tmp_path, acquisitions)
    projection = result["rows"][0]["policy_projection"]
    assert projection["admission"] == "not_evaluated_without_source_reproduction"
    assert projection["rules"][0]["terms"][0]["matches"] is False
    assert result["rows"][1]["policy_projection"]["rules"] == ()
    for field, value in (
        ("source_ids", ("missing-source",)),
        ("source_profiles", ("wrong-profile",)),
        ("metric_ids", ("invented.metric",)),
    ):
        changed = manifest.model_copy(
            update={"rows": (row.model_copy(update={field: value}),)}
        )
        path.write_bytes(canonical_bytes(changed))
        with pytest.raises(ValueError):
            matrix.verify_matrix(path, tmp_path, acquisitions)
    path.write_bytes(canonical_bytes(manifest))
    (tmp_path / "research-pages/terms.html").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash differs"):
        matrix.verify_matrix(path, tmp_path, acquisitions)


def test_matrix_refuses_unsupported_permission_claim_and_keeps_scoped_terms(cohort):
    import verify_source_research_matrix as matrix
    from fundamental_service.terms_content import HtmlTermsScopeV1, terms_content_digest

    row = matrix_row(cohort)
    supported = matrix.ResearchUse(
        status="evidence_supported",
        reason="A research claim does not authorize runtime",
    )
    row = row.model_copy(
        update={"rights": row.rights.model_copy(update={"analysis": supported})}
    )
    with pytest.raises(ValueError, match="differs from installed policy/evidence"):
        matrix.project_policy(row, free_market_source_policy(), {})
    scope = HtmlTermsScopeV1(tag="article", attribute="id", value="terms")
    first = b'<html><header>Old</header><article id="terms">Exact restriction</article></html>'
    second = first.replace(b"Old", b"New wrapper")
    assert sha256(first).hexdigest() != sha256(second).hexdigest()
    assert terms_content_digest(first, scope) == terms_content_digest(second, scope)


def test_extension_localname_and_prefix_cannot_become_standard_anchor(
    cohort, sec_evidence
):
    root, _ = sec_evidence
    artifact = ArtifactStore(root / "artifacts")
    report = coverage.ParserEvidence.model_validate_json(
        artifact.read("source-coverage-parser:tsla-fy2023-original")
    ).report
    extension = coverage.ParsedXbrlFactV1(
        concept="us-gaap:Assets",
        namespace_uri="http://www.tesla.com/20231231",
        value="999999",
        context_id="extension-context",
    )
    report = report.model_copy(update={"facts": (extension,)})
    case = cohort.cases[1]
    manifest = coverage.CaptureManifest.model_validate_json(
        (coverage.REPOSITORY / cohort.source_manifest).read_bytes()
    )
    entry = next(item for item in manifest.sources if item.path == case.filing_path)
    original = coverage.OriginalInventory(
        inline_qnames=("custom:Assets",),
        declared_namespaces={"custom": "http://www.tesla.com/20231231"},
        schema_resource_urls=(),
    )
    result = coverage.observe_sec(case, report, entry, original)
    assert result["observations"]["balance_sheet"] == ()
    assert (
        result["original_queries"]["balance_sheet"]["disposition"]
        == "queried_qnames_absent_from_original"
    )


def test_completed_sec_replay_cannot_repair_missing_report(
    tmp_path, monkeypatch, cohort, sec_evidence
):
    source, _ = sec_evidence
    root = tmp_path / "missing-report"
    shutil.copytree(source, root)
    log = root / "artifacts/.artifact-records.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()]
    log.write_text(
        "\n".join(
            json.dumps(record)
            for record in records
            if record["artifact_id"] != "source-coverage-parser:aapl-fy2024-original"
        )
        + "\n"
    )
    monkeypatch.setattr(coverage, "parse_filing_offline", forbidden)
    with pytest.raises(ValueError, match="missing a retained parser report"):
        coverage.reproduce_sec(cohort, root)


def test_supported_matrix_row_cannot_borrow_unreferenced_terms(
    public_evidence, cohort, monkeypatch
):
    import verify_source_research_matrix as matrix

    root = public_evidence
    (root / "research-pages").mkdir()
    (root / "research-pages/terms.html").write_bytes(TEST_TERMS)
    unrelated = b"<html>Unrelated SEC access evidence.</html>"
    (root / "research-pages/sec-access.html").write_bytes(unrelated)
    terms = matrix.ResearchEvidence(
        evidence_id="test-terms",
        uri="https://www.govinfo.gov/content/pkg/USCODE-2024-title17/html/USCODE-2024-title17-chap1-sec105.htm",
        checked_on=AT.date(),
        content_sha256=sha256(TEST_TERMS).hexdigest(),
        boundary="whole document",
        quote="Synthetic test-only government works notice.",
        status="captured",
        artifact_ref="research-pages/terms.html",
    )
    sec = terms.model_copy(
        update={
            "evidence_id": "sec-access",
            "uri": "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data",
            "content_sha256": sha256(unrelated).hexdigest(),
            "quote": "Unrelated SEC access evidence.",
            "artifact_ref": "research-pages/sec-access.html",
        }
    )
    row = matrix_row(cohort)
    supported = matrix.ResearchUse(
        status="evidence_supported", reason="This row cites its exact test terms"
    )
    row = row.model_copy(
        update={"rights": row.rights.model_copy(update={"analysis": supported})}
    )
    manifest = matrix.Matrix(
        protocol="source-use-research-matrix-v1",
        checked_on=AT.date(),
        rows=(row,),
        evidence=(terms, sec),
    )
    path = root / "matrix.json"
    path.write_bytes(canonical_bytes(manifest))
    acquisitions = PublicSourceAcquisition(
        provider=PublicSourceAdapter(user_agent="Test <test@example.invalid>"),
        artifacts=ArtifactStore(root / "artifacts"),
        content=FilesystemContentStore(root / "content"),
        capture_lock=lambda _: nullcontext(),
    )
    monkeypatch.setattr(
        matrix,
        "load_runtime_source_use_policy",
        coverage.load_runtime_source_use_policy,
    )
    result = matrix.verify_matrix(path, root, acquisitions)
    assert (
        result["rows"][0]["policy_projection"]["rules"][0]["terms"][0]["matches"]
        is True
    )
    wrong_reference = row.model_copy(update={"evidence_refs": ("sec-access",)})
    path.write_bytes(
        canonical_bytes(manifest.model_copy(update={"rows": (wrong_reference,)}))
    )
    with pytest.raises(ValueError, match="differs from installed policy/evidence"):
        matrix.verify_matrix(path, root, acquisitions)
    unconfirmed = wrong_reference.model_copy(
        update={"rights": matrix_row(cohort).rights}
    )
    path.write_bytes(
        canonical_bytes(manifest.model_copy(update={"rows": (unconfirmed,)}))
    )
    result = matrix.verify_matrix(path, root, acquisitions)
    assert (
        result["rows"][0]["policy_projection"]["rules"][0]["terms"][0]["matches"]
        is None
    )


@pytest.mark.parametrize("changed_field", ["source_version", "series_id", "provider"])
def test_matrix_rejects_capture_registration_drift_despite_unchanged_policy(
    tmp_path, cohort, monkeypatch, changed_field
):
    from dataclasses import replace

    import verify_source_research_matrix as matrix

    row = matrix_row(cohort, evidence_refs=())
    manifest = matrix.Matrix(
        protocol="source-use-research-matrix-v1",
        checked_on=AT.date(),
        rows=(row,),
        evidence=(),
    )
    path = tmp_path / "matrix.json"
    path.write_bytes(canonical_bytes(manifest))
    registrations = matrix.default_public_source_registrations()
    changes = {
        "source_version": "treasury-unreviewed-v2",
        "series_id": "unreviewed.metric",
        "provider": matrix.default_macro_providers()[0],
    }
    changed_registrations = tuple(
        replace(
            item,
            profile=replace(item.profile, **{changed_field: changes[changed_field]}),
        )
        if item.spec.source_id == row.source_ids[0]
        else item
        for item in registrations
    )
    monkeypatch.setattr(
        matrix, "default_public_source_registrations", lambda: changed_registrations
    )
    acquisitions = PublicSourceAcquisition(
        provider=PublicSourceAdapter(user_agent="Test <test@example.invalid>"),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        content=FilesystemContentStore(tmp_path / "content"),
        capture_lock=lambda _: nullcontext(),
    )
    with pytest.raises(ValueError, match="capture registration drifted"):
        matrix.verify_matrix(path, tmp_path, acquisitions)
