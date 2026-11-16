"""Original-source and negative acceptance for the opt-in taxonomy correction."""

import hashlib
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fundamental_service import historical_dqc_config
from fundamental_service.arelle_parser import (
    ArelleValidationProfileV1,
    fact_semantic_digest,
    parse_filing_offline,
)
from fundamental_service.historical_dqc import V3_2012_PROFILE, V3_2013_PROFILE
from fundamental_service.historical_dqc_config import (
    CONFIG_SOURCES,
    TAXONOMY_SHA256,
    generate_axis_config,
    publish_axis_config,
)
from fundamental_service.regulatory_validation import require_sec_validation_evidence
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError


@pytest.fixture
def evidence_root():
    configured = os.environ.get("ISSUE371_EVIDENCE_ROOT")
    if not configured:
        pytest.skip(
            "original FASB/SEC captures and pinned offline resources are not configured"
        )
    return Path(configured)


def taxonomy_path(root, year):
    if year == 2012:
        return (
            root
            / f"historical-delivery/official-taxonomies/{CONFIG_SOURCES[year].sha256}.zip"
        )
    return root / f"issue377-history-windows/research/{TAXONOMY_SHA256}.zip"


@pytest.mark.parametrize("year", (2012, 2013))
def test_profile_rejects_another_years_archive_before_loading(
    evidence_root, tmp_path, year
):
    other_year = 2013 if year == 2012 else 2012
    with pytest.raises(ValueError, match=f"FASB {year} taxonomy archive hash"):
        generate_axis_config(
            taxonomy_archive=taxonomy_path(evidence_root, other_year),
            official_root=tmp_path,
            taxonomy_cache=tmp_path,
            taxonomy_year=year,
        )


def test_config_builder_rejects_an_unpinned_archive_before_loading(tmp_path):
    archive = tmp_path / "taxonomy.zip"
    archive.write_bytes(b"not-the-pinned-taxonomy")
    with pytest.raises(ValueError, match="archive hash"):
        generate_axis_config(
            taxonomy_archive=archive, official_root=tmp_path, taxonomy_cache=tmp_path
        )


@pytest.mark.parametrize("year", (2012, 2013))
def test_original_config_build_reuses_artifacts_without_regeneration(
    evidence_root, tmp_path, monkeypatch, year
):
    root = evidence_root
    artifacts = ArtifactStore(tmp_path)
    parameters = dict(
        taxonomy_archive=taxonomy_path(root, year),
        official_root=root / "parser-resources/historical-v3",
        taxonomy_cache=root / "source-parser-cache",
        artifacts=artifacts,
        implementation_commit="a" * 40,
        taxonomy_year=year,
    )
    first = publish_axis_config(**parameters)
    config = json.loads(artifacts.read(first["config_artifact_id"]))
    assert len(config) == 22
    assert (
        "EstimateOfFairValueFairValueDisclosureMember"
        in config["FairValueByFairValueHierarchyLevelAxis"]["defined_members"]
    )
    assert first["output_digest"] == CONFIG_SOURCES[year].profile.axis_config_sha256
    before = {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()
    }
    monkeypatch.setattr(
        historical_dqc_config,
        "generate_axis_config",
        lambda **kwargs: pytest.fail("a completed build must not regenerate"),
    )
    second = publish_axis_config(**parameters)
    assert second["input_digest"] == first["input_digest"]
    assert not second["wrote"] and not second["generated"]
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()
    }
    # Completed receipts cannot hide corruption of the content they reference.
    for path in tmp_path.iterdir():
        if path.read_bytes() == canonical_bytes(config):
            path.write_bytes(b"{}")
            break
    else:
        pytest.fail("config artifact missing")
    with pytest.raises(SnapshotError) as error:
        publish_axis_config(**parameters)
    assert error.value.code == "ARTIFACT_HASH_MISMATCH"


@pytest.mark.parametrize(
    "year,profile,previous_digest,fact_count",
    (
        (
            2012,
            V3_2012_PROFILE,
            "9edcb319e3fe771f01492c09add4c59ff5492bfe8cd104a2e333b00af001d258",
            1965,
        ),
        (
            2013,
            V3_2013_PROFILE,
            "392e28526dbd089b43f6bbfe5c23367c1ae7710a6e701186a70cfabf8d62cadc",
            2508,
        ),
    ),
)
def test_real_original_valid_members_pass_but_invalid_members_still_block(
    evidence_root, tmp_path, year, profile, previous_digest, fact_count
):
    root = evidence_root
    previous_raw = (
        root / f"checkpoint-4fb5e85e/earlier-originals/{previous_digest}.json"
    ).read_bytes()
    assert hashlib.sha256(previous_raw).hexdigest() == previous_digest
    previous = json.loads(previous_raw)
    selection = previous["inputs"]["selection"]
    config = generate_axis_config(
        taxonomy_archive=taxonomy_path(root, year),
        official_root=root / "parser-resources/historical-v3",
        taxonomy_cache=root / "source-parser-cache",
        taxonomy_year=year,
    )
    config_path = tmp_path / "config.json"
    config_path.write_bytes(canonical_bytes(config))
    old_profile = ArelleValidationProfileV1.model_validate(
        previous["output"]["report"]["validation_profile"]
    )
    new_profile = ArelleValidationProfileV1.model_validate(
        {
            **old_profile.model_dump(mode="json"),
            "profile_id": profile.profile_id,
            "dqc_version": profile.dqc_version,
            "historical_dqc_axis_config": str(config_path),
        }
    )
    archive_hash = selection["archive"]["content_hash"]
    archive_paths = (
        [root / f"sec-content/{archive_hash[:2]}/{archive_hash}.bin"]
        if year == 2012
        else list(
            (root / "issue377-history-windows/capture/content").rglob(
                archive_hash + ".*"
            )
        )
    )
    assert len(archive_paths) == 1
    assert hashlib.sha256(archive_paths[0].read_bytes()).hexdigest() == archive_hash
    stage = tmp_path / "source"
    stage.mkdir()
    with zipfile.ZipFile(archive_paths[0]) as archive:
        for member in selection["members"]:
            name = member["filename"]
            assert Path(name).name == name
            raw = archive.read(name)
            assert hashlib.sha256(raw).hexdigest() == member["content_hash"]
            (stage / name).write_bytes(raw)

    def parse(profile):
        return parse_filing_offline(
            stage / selection["primary_document"],
            profile=profile,
            taxonomy_version=f"us-gaap-{year}",
            taxonomy_cache_dir=root / "source-parser-cache",
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=180),
        )

    old = parse(old_profile)
    assert sum(f.code == "DQC.US.0001.51" for f in old.findings) > 0
    assert old.blocking_finding_codes() == ("DQC.US.0001.51",)
    original = parse(new_profile)
    require_sec_validation_evidence(original)
    assert len(original.facts) == len(old.facts) == fact_count
    assert fact_semantic_digest(original) == fact_semantic_digest(old)
    assert not original.blocking_finding_codes()
    assert original.replay_digest() == parse(new_profile).replay_digest()
    assert original.validation_profile_digest != old.validation_profile_digest
    assert original.network_attempt_count == 0
    # A source mutation is a synthetic negative fixture, never an SEC observation.
    presentation = stage / f"neu-{year}1231_pre.xml"
    raw = presentation.read_bytes()
    assert raw.count(b"#us-gaap_EstimateOfFairValueFairValueDisclosureMember") == 2
    presentation.write_bytes(
        raw.replace(
            b"#us-gaap_EstimateOfFairValueFairValueDisclosureMember",
            b"#us-gaap_CommonStockMember",
        )
    )
    invalid = parse(new_profile)
    require_sec_validation_evidence(invalid)
    assert "DQC.US.0001.51" in invalid.blocking_finding_codes()
    assert any(
        f.code == "DQC.US.0001.51" and f.rule_severity == "error"
        for f in invalid.findings
    )
