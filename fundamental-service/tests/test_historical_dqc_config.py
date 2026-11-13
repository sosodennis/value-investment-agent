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
from fundamental_service.historical_dqc import V3_2013_PROFILE
from fundamental_service.historical_dqc_config import (
    TAXONOMY_SHA256,
    generate_axis_config,
    publish_axis_config,
)
from fundamental_service.regulatory_validation import require_sec_validation_evidence
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes


@pytest.fixture
def evidence_root():
    configured = os.environ.get("ISSUE371_EVIDENCE_ROOT")
    if not configured:
        pytest.skip(
            "original FASB/SEC captures and pinned offline resources are not configured"
        )
    return Path(configured)


def test_config_builder_rejects_an_unpinned_archive_before_loading(tmp_path):
    archive = tmp_path / "taxonomy.zip"
    archive.write_bytes(b"not-the-pinned-taxonomy")
    with pytest.raises(ValueError, match="archive hash"):
        generate_axis_config(
            taxonomy_archive=archive, official_root=tmp_path, taxonomy_cache=tmp_path
        )


def test_original_config_build_reuses_artifacts_without_regeneration(
    evidence_root, tmp_path, monkeypatch
):
    root = evidence_root
    artifacts = ArtifactStore(tmp_path)
    parameters = dict(
        taxonomy_archive=root
        / f"issue377-history-windows/research/{TAXONOMY_SHA256}.zip",
        official_root=root / "parser-resources/historical-v3",
        taxonomy_cache=root / "source-parser-cache",
        artifacts=artifacts,
        implementation_commit="a" * 40,
    )
    first = publish_axis_config(**parameters)
    config = json.loads(artifacts.read(first["config_artifact_id"]))
    assert len(config) == 22
    assert (
        "EstimateOfFairValueFairValueDisclosureMember"
        in config["FairValueByFairValueHierarchyLevelAxis"]["defined_members"]
    )
    assert first["output_digest"] == V3_2013_PROFILE.axis_config_sha256
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


def test_real_original_valid_members_pass_but_invalid_members_still_block(
    evidence_root, tmp_path
):
    root = evidence_root
    previous = json.loads(
        (
            root
            / "checkpoint-4fb5e85e/earlier-originals/392e28526dbd089b43f6bbfe5c23367c1ae7710a6e701186a70cfabf8d62cadc.json"
        ).read_bytes()
    )
    selection = previous["inputs"]["selection"]
    config = generate_axis_config(
        taxonomy_archive=root
        / f"issue377-history-windows/research/{TAXONOMY_SHA256}.zip",
        official_root=root / "parser-resources/historical-v3",
        taxonomy_cache=root / "source-parser-cache",
    )
    config_path = tmp_path / "config.json"
    config_path.write_bytes(canonical_bytes(config))
    old_profile = ArelleValidationProfileV1.model_validate(
        previous["output"]["report"]["validation_profile"]
    )
    new_profile = ArelleValidationProfileV1.model_validate(
        {
            **old_profile.model_dump(mode="json"),
            "profile_id": V3_2013_PROFILE.profile_id,
            "dqc_version": V3_2013_PROFILE.dqc_version,
            "historical_dqc_axis_config": str(config_path),
        }
    )
    archive_hash = "813fafd57f1c21b2a7de349b4966329f4f009163b4e16ca2c85e0d621449c5c1"
    archive_paths = list(
        (root / "issue377-history-windows/capture/content").rglob(archive_hash + ".*")
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
            taxonomy_version="us-gaap-2013",
            taxonomy_cache_dir=root / "source-parser-cache",
            deadline_at=datetime.now(timezone.utc) + timedelta(seconds=180),
        )

    old = parse(old_profile)
    assert sum(f.code == "DQC.US.0001.51" for f in old.findings) == 48
    assert old.blocking_finding_codes() == ("DQC.US.0001.51",)
    original = parse(new_profile)
    require_sec_validation_evidence(original)
    assert len(original.facts) == len(old.facts) == 2508
    assert fact_semantic_digest(original) == fact_semantic_digest(old)
    assert not original.blocking_finding_codes()
    assert original.replay_digest() == parse(new_profile).replay_digest()
    assert original.validation_profile_digest != old.validation_profile_digest
    assert original.network_attempt_count == 0
    # A source mutation is a synthetic negative fixture, never an SEC observation.
    presentation = stage / "neu-20131231_pre.xml"
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
