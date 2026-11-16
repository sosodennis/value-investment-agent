from hashlib import sha256
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import (
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
)
from fundamental_service.dqc_ruleset_plugin import select_loaded_ruleset
from fundamental_service.dqc_rulesets import DqcRulesetBindingV1, DqcRulesetCatalogV1
from fundamental_service.regulatory_validation import require_sec_validation_evidence
from fundamental_service.snapshots import SnapshotError


def catalog(tmp_path: Path) -> DqcRulesetCatalogV1:
    bindings = []
    for year in (2025, 2026):
        path = tmp_path / f"dqc-us-{year}-V31-ruleset.zip"
        raw = f"ruleset-{year}".encode()
        path.write_bytes(raw)
        bindings.append(
            DqcRulesetBindingV1(
                taxonomy_namespace=f"http://fasb.org/us-gaap/{year}",
                path=path,
                sha256=sha256(raw).hexdigest(),
            )
        )
    return DqcRulesetCatalogV1(bindings=tuple(bindings))


def test_loaded_taxonomy_selects_its_pinned_ruleset(tmp_path: Path) -> None:
    rules = catalog(tmp_path)
    options = SimpleNamespace(
        fundamental_dqc_ruleset_catalog=rules.model_dump_json(),
        xule_rule_set="wrong-2024.zip",
    )
    controller = SimpleNamespace()
    model = SimpleNamespace(
        namespaceDocs={
            "http://nve.com/20250331": object(),
            "http://fasb.org/us-gaap/2025": object(),
        }
    )
    select_loaded_ruleset(controller, options, model)
    assert options.xule_rule_set == str(rules.bindings[0].path)
    assert controller.fundamental_dqc_ruleset_binding == rules.bindings[0]


@pytest.mark.parametrize(
    "namespaces",
    [
        (),
        ("http://fasb.org/us-gaap/2024",),
        ("http://fasb.org/us-gaap/2025", "http://fasb.org/us-gaap/2026"),
    ],
)
def test_missing_or_mixed_taxonomy_has_no_fallback(
    tmp_path: Path, namespaces: tuple[str, ...]
) -> None:
    rules = catalog(tmp_path)
    with pytest.raises(ArelleParserError) as failure:
        select_loaded_ruleset(
            SimpleNamespace(),
            SimpleNamespace(
                fundamental_dqc_ruleset_catalog=rules.model_dump_json(),
                xule_rule_set="2024.zip",
            ),
            SimpleNamespace(namespaceDocs=dict.fromkeys(namespaces)),
        )
    assert failure.value.code == "DQC_TAXONOMY_RULESET_UNAVAILABLE"


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_corrupt_ruleset_refuses_before_validation(
    tmp_path: Path, missing: bool
) -> None:
    rules = catalog(tmp_path)
    if missing:
        rules.bindings[0].path.unlink()
    else:
        rules.bindings[0].path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash does not match"):
        rules.verify_files()


def test_duplicate_or_reordered_bindings_refuse(tmp_path: Path) -> None:
    rules = catalog(tmp_path)
    for bindings in (rules.bindings[::-1], (rules.bindings[0], rules.bindings[0])):
        with pytest.raises(ValidationError, match="unique and canonical"):
            DqcRulesetCatalogV1(bindings=bindings)


def test_default_profile_does_not_add_catalog_to_its_identity() -> None:
    profile = ArelleValidationProfileV1(profile_id="sec-efm-us-gaap-v1")
    assert "dqc_ruleset_catalog" not in profile.model_dump(mode="json")


def test_parse_only_profile_cannot_claim_taxonomy_dqc(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="modern SEC validation"):
        ArelleValidationProfileV1(
            profile_id="parse-only", dqc_ruleset_catalog=catalog(tmp_path)
        )


def validation_profile(
    tmp_path: Path, rules: DqcRulesetCatalogV1
) -> ArelleValidationProfileV1:
    return ArelleValidationProfileV1(
        profile_id="sec-efm-us-dqc-v31.0.3",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=tmp_path,
        xule_plugin_dir=tmp_path,
        dqc_ruleset_path=tmp_path / "default.zip",
        edgar_plugin_sha256="1" * 64,
        xule_plugin_sha256="2" * 64,
        dqc_ruleset_sha256="3" * 64,
        dqc_ruleset_catalog=rules,
    )


def test_catalog_profile_digest_survives_deployment_path_changes(
    tmp_path: Path,
) -> None:
    rules = catalog(tmp_path)
    profile = validation_profile(tmp_path, rules)
    moved = rules.model_copy(
        update={
            "bindings": tuple(
                item.model_copy(
                    update={"path": Path("/run/deployment") / item.path.name}
                )
                for item in rules.bindings
            )
        }
    )
    assert (
        profile.digest()
        == profile.model_copy(update={"dqc_ruleset_catalog": moved}).digest()
    )
    changed = rules.model_copy(
        update={
            "bindings": (
                rules.bindings[0].model_copy(update={"sha256": "0" * 64}),
                rules.bindings[1],
            )
        }
    )
    assert (
        profile.digest()
        != profile.model_copy(update={"dqc_ruleset_catalog": changed}).digest()
    )


def test_serving_requires_exact_full_ruleset_selection_evidence(tmp_path: Path) -> None:
    rules = catalog(tmp_path)
    profile = validation_profile(tmp_path, rules)
    marker = (
        "dqc-full-taxonomy-ruleset-v1:"
        + rules.bindings[0].taxonomy_namespace
        + ":"
        + rules.bindings[0].sha256
    )
    report = ArelleParseReportV1(
        filing_path="original.xbrl",
        parser_version="2.47.4",
        taxonomy_version="2025",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        facts=(
            ParsedXbrlFactV1(
                concept="us-gaap:Assets",
                namespace_uri=rules.bindings[0].taxonomy_namespace,
                value="1",
                context_id="c",
            ),
        ),
        validation_engines=("sec-efm", "dqc-us"),
        validation_evidence=(
            "strict-sec-efm-profile-selected",
            "dqc-dqcrt-checks-completed",
            marker,
        ),
        parsed_at=datetime.now(UTC),
    )
    require_sec_validation_evidence(report)
    with pytest.raises(SnapshotError) as failure:
        require_sec_validation_evidence(
            report.model_copy(
                update={"validation_evidence": report.validation_evidence[:-1]}
            )
        )
    assert failure.value.code == "VALIDATION_EVIDENCE_MISSING"
    with pytest.raises(SnapshotError) as failure:
        require_sec_validation_evidence(
            report.model_copy(
                update={
                    "facts": (
                        report.facts[0].model_copy(
                            update={
                                "namespace_uri": rules.bindings[1].taxonomy_namespace
                            }
                        ),
                    )
                }
            )
        )
    assert failure.value.code == "VALIDATION_EVIDENCE_MISSING"
