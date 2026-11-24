from datetime import date, datetime, timezone
import json
import os
import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
    _directory_hash,
    parse_filing_offline,
)
from fundamental_service.dqc_applicability import (
    DqcFilingContextV1,
    dqc_applicability_policy_digest,
)
from fundamental_service.dqc_rulesets import (
    DQC_V18_CONSTANTS_MARKER,
    DQC_V18_PROFILE_ID,
    DQC_V18_RULESETS,
    DqcRulesetBindingV1,
    DqcRulesetCatalogV1,
)
from fundamental_service.dqc_resource_packages import (
    V18_PACKAGE_MARKER,
    V18_PACKAGE_SHA256,
)
from fundamental_service.regulatory_validation import bind_dqc_filing_context
from fundamental_service.regulatory_validation import require_sec_validation_evidence
from fundamental_service.snapshots import SnapshotError


def _catalog(root: Path) -> DqcRulesetCatalogV1:
    return DqcRulesetCatalogV1(
        dqc_version="v18",
        bindings=tuple(
            DqcRulesetBindingV1(
                taxonomy_namespace=namespace,
                path=root / name,
                sha256=digest,
            )
            for namespace, (name, digest) in DQC_V18_RULESETS.items()
        ),
    )


def _profile(root: Path) -> ArelleValidationProfileV1:
    catalog = _catalog(root)
    binding = catalog.bindings[-1]
    return ArelleValidationProfileV1(
        profile_id=DQC_V18_PROFILE_ID,
        dqc_version="v18",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=root / "EDGAR",
        xule_plugin_dir=root / "xule",
        dqc_ruleset_path=binding.path,
        edgar_plugin_sha256="1" * 64,
        xule_plugin_sha256="2" * 64,
        dqc_ruleset_sha256=binding.sha256,
        dqc_ruleset_catalog=catalog,
        dqc_applicability_digest=dqc_applicability_policy_digest("v18"),
    )


def test_v18_selects_exact_namespace_including_legacy_date_suffix(tmp_path: Path):
    catalog = _catalog(tmp_path)
    selected = catalog.select(("http://fasb.org/us-gaap/2020-01-31",))
    assert selected.path.name == "dqc-us-2020-v18-xule30055-build-v1.zip"
    with pytest.raises(ValueError, match="unique pinned"):
        catalog.select(("http://fasb.org/us-gaap/2020",))
    with pytest.raises(ValueError, match="unique pinned"):
        catalog.select(("http://fasb.org/us-gaap/2022", "http://fasb.org/us-gaap/2023"))


def test_v18_catalog_rejects_a_substituted_or_renamed_ruleset(tmp_path: Path):
    raw = _catalog(tmp_path).model_dump(mode="json")
    for field, value in (("sha256", "0" * 64), ("path", "dqc-us-2024-V31-ruleset.zip")):
        changed = {**raw, "bindings": [dict(item) for item in raw["bindings"]]}
        changed["bindings"][0][field] = value
        with pytest.raises(ValidationError, match="pinned official"):
            DqcRulesetCatalogV1.model_validate(changed)


def test_v18_profile_cannot_masquerade_as_v31(tmp_path: Path):
    profile = _profile(tmp_path)
    raw = profile.model_dump(mode="json")
    raw["profile_id"] = "sec-efm-us-dqc-v31.0.3"
    raw["dqc_version"] = "v31.0.3"
    raw["dqc_applicability_digest"] = dqc_applicability_policy_digest()
    with pytest.raises(ValidationError, match="catalog version"):
        ArelleValidationProfileV1.model_validate(raw)
    catalog = _catalog(tmp_path).model_dump(mode="json")
    catalog["dqc_version"] = "v31.0.3"
    with pytest.raises(ValidationError, match="cannot be declared"):
        DqcRulesetCatalogV1.model_validate(catalog)
    raw = profile.model_dump(mode="json")
    raw.pop("dqc_ruleset_catalog")
    with pytest.raises(ValidationError, match="exact pinned full catalog"):
        ArelleValidationProfileV1.model_validate(raw)


def test_v18_missing_or_corrupt_file_refuses_without_fallback(tmp_path: Path):
    catalog = _catalog(tmp_path)
    with pytest.raises(ValueError, match="hash does not match"):
        catalog.verify_files()
    for binding in catalog.bindings:
        binding.path.write_bytes(b"substituted")
    with pytest.raises(ValueError, match="hash does not match"):
        catalog.verify_files()


def _bound_report(root: Path, findings: tuple[ArelleFindingV1, ...]):
    profile = _profile(root)
    marker = profile.dqc_ruleset_catalog.bindings[-1]
    report = ArelleParseReportV1(
        filing_path="original.htm",
        parser_version="2.47.4",
        taxonomy_version="us-gaap-2022",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        findings=findings,
        validation_engines=("sec-efm", "dqc-us"),
        validation_evidence=(
            "strict-sec-efm-profile-selected",
            "dqc-dqcrt-checks-completed",
            DQC_V18_CONSTANTS_MARKER,
            f"{V18_PACKAGE_MARKER}:{V18_PACKAGE_SHA256}",
            f"dqc-full-taxonomy-ruleset-v1:{marker.taxonomy_namespace}:{marker.sha256}",
        ),
        facts=(
            ParsedXbrlFactV1(
                concept="us-gaap:Assets",
                namespace_uri=marker.taxonomy_namespace,
                context_id="c",
                value="1",
            ),
        ),
        parsed_at=datetime(2026, 11, 24, tzinfo=timezone.utc),
    )
    context = DqcFilingContextV1(
        issuer_id="0000320193",
        accession_number="0000320193-22-000108",
        filing_date=date(2022, 10, 28),
        dqc_version="v18",
        policy_digest=dqc_applicability_policy_digest("v18"),
    )
    return report, context


def test_v18_applicability_does_not_read_v31_fallback_dates(tmp_path: Path):
    finding = ArelleFindingV1(
        code="DQC.US.0243.10944", severity="error", message="unknown V18 assertion"
    )
    report, context = _bound_report(tmp_path, (finding,))
    bound = bind_dqc_filing_context(report, context)
    decision = bound.finding_applicability(finding)
    assert decision.status == "unknown"
    assert decision.document_sha256 is None
    assert bound.blocking_finding_codes() == (finding.code,)


def test_v18_official_emitted_date_controls_affected_finding(tmp_path: Path):
    future = ArelleFindingV1(
        code="DQC.US.0004.16",
        severity="error",
        rule_effective_date=date(2022, 11, 1),
        message="official rule diagnostic",
    )
    report, context = _bound_report(tmp_path, (future,))
    bound = bind_dqc_filing_context(report, context)
    assert bound.finding_applicability(future).status == "future"
    assert bound.blocking_finding_codes() == ()
    active_context = context.model_copy(update={"filing_date": date(2022, 11, 1)})
    active = bind_dqc_filing_context(report, active_context)
    assert active.blocking_finding_codes() == (future.code,)


def test_v18_requires_complete_source_constant_evaluation_evidence(tmp_path: Path):
    report, _ = _bound_report(tmp_path, ())
    incomplete = report.model_copy(
        update={
            "validation_evidence": tuple(
                marker
                for marker in report.validation_evidence
                if marker != DQC_V18_CONSTANTS_MARKER
            )
        }
    )
    with pytest.raises(SnapshotError) as failure:
        require_sec_validation_evidence(incomplete)
    assert failure.value.code == "VALIDATION_EVIDENCE_MISSING"
    require_sec_validation_evidence(report)


def test_v18_filing_date_identity_survives_retained_replay(tmp_path: Path):
    finding = ArelleFindingV1(
        code="DQC.US.0004.16",
        severity="error",
        rule_effective_date=date(2022, 11, 1),
        message="official rule diagnostic",
    )
    report, context = _bound_report(tmp_path, (finding,))
    bound = bind_dqc_filing_context(report, context)
    replay = ArelleParseReportV1.model_validate_json(bound.model_dump_json())
    assert replay.replay_digest() == bound.replay_digest()
    assert replay.dqc_filing_context.dqc_version == "v18"
    assert replay.validation_profile.profile_id == DQC_V18_PROFILE_ID
    wrong_context = context.model_copy(
        update={
            "dqc_version": "v31.0.3",
            "policy_digest": dqc_applicability_policy_digest(),
        }
    )
    with pytest.raises(ValidationError, match="matching validation evidence"):
        bind_dqc_filing_context(report, wrong_context)


def test_retained_apple_2022_completes_full_v18_offline_and_preserves_primary_numbers(
    tmp_path: Path,
):
    names = (
        "ISSUE494_V18_CATALOG_PATH",
        "ISSUE494_V18_EDGAR_DIR",
        "ISSUE494_V18_XULE_DIR",
        "ISSUE494_V18_CACHE_DIR",
        "ISSUE494_V18_APPLE_2022_ARCHIVE_PATH",
    )
    if not all(os.environ.get(name) for name in names):
        pytest.skip("pinned V18 resources and retained Apple FY2022 are not configured")
    catalog = DqcRulesetCatalogV1.model_validate_json(
        Path(os.environ[names[0]]).read_bytes()
    )
    edgar, xule = Path(os.environ[names[1]]), Path(os.environ[names[2]])
    binding = catalog.bindings[0]
    profile = ArelleValidationProfileV1(
        profile_id=DQC_V18_PROFILE_ID,
        dqc_version="v18",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=edgar,
        xule_plugin_dir=xule,
        dqc_ruleset_path=binding.path,
        edgar_plugin_sha256=_directory_hash(edgar),
        xule_plugin_sha256=_directory_hash(xule),
        dqc_ruleset_sha256=binding.sha256,
        dqc_ruleset_catalog=catalog,
        dqc_applicability_digest=dqc_applicability_policy_digest("v18"),
    )
    golden = json.loads(
        (
            Path(__file__).parent / "fixtures/annual-statements/issue494-golden.json"
        ).read_bytes()
    )
    original = next(
        item
        for item in golden["filings"]
        if item["accession_number"] == "0000320193-22-000108"
    )
    cohort = json.loads(
        (
            Path(__file__).parent / "fixtures/annual-statements/issue494-cohort.json"
        ).read_bytes()
    )
    filing = next(
        item
        for item in cohort["filings"]
        if item["accession_number"] == original["accession_number"]
    )
    archive_receipt = next(
        record
        for record in filing["source_records"]
        if record["uri"].endswith("-xbrl.zip")
    )
    archive_path = Path(os.environ[names[4]])
    assert (
        hashlib.sha256(archive_path.read_bytes()).hexdigest()
        == archive_receipt["content_hash"]
    )
    with ZipFile(archive_path) as archive:
        archive.extractall(tmp_path)
    filing_path = tmp_path / filing["primary_document"]
    report = parse_filing_offline(
        filing_path,
        profile=profile,
        taxonomy_version="us-gaap-2022",
        taxonomy_cache_dir=Path(os.environ[names[3]]),
        source_content_hash=hashlib.sha256(filing_path.read_bytes()).hexdigest(),
    )
    require_sec_validation_evidence(report)
    bound = bind_dqc_filing_context(
        report,
        DqcFilingContextV1(
            issuer_id="0000320193",
            accession_number=original["accession_number"],
            filing_date=date(2022, 10, 28),
            dqc_version="v18",
            policy_digest=dqc_applicability_policy_digest("v18"),
        ),
    )
    assert bound.validation_engines == ("sec-efm", "dqc-us")
    assert bound.network_attempt_count == 0
    assert bound.blocking_finding_codes() == ()
    selected = catalog.select(("http://fasb.org/us-gaap/2022",))
    assert (
        f"dqc-full-taxonomy-ruleset-v1:{selected.taxonomy_namespace}:{selected.sha256}"
        in bound.validation_evidence
    )
    observed = {(fact.concept, fact.context_id, fact.value) for fact in bound.facts}
    expected = {
        (value["concept_qname"], value["context_id"], value["value"])
        for statement in original["statements"]
        for row in statement["rows"]
        if row["status"] == "reported"
        for value in row["values"]
    }
    assert expected <= observed
    assert (
        ArelleParseReportV1.model_validate_json(bound.model_dump_json()).replay_digest()
        == bound.replay_digest()
    )
