"""Version boundaries keep execution proofs separate from stable identities."""

from pathlib import Path

import pytest

from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.parser_action_evidence import require_parser_action_evidence
from fundamental_service.parser_action_identity import (
    ParserBuildChecks,
    parser_action_input,
)
from fundamental_service.parser_action_contracts import (
    ParserActionInputV3,
    ParserBuildIdentityV1,
)
from fundamental_service.snapshots import SnapshotError
from test_parser_actions import case, issuer


@pytest.mark.parametrize("field", ("execution_evidence", "identity_protocol", "marker"))
def test_raw_execution_body_cannot_claim_downstream_representation(tmp_path, field):
    c = case(tmp_path)
    changes = {
        "execution_evidence": {"execution_evidence": ("disguised-proof",)},
        "identity_protocol": {"identity_protocol": "parser-report-computation-v1"},
        "marker": {
            "validation_evidence": (
                *c.execute().validation_evidence,
                "sec-parser-computation-v1:forged",
            )
        },
    }
    with pytest.raises(SnapshotError, match="parser body identity differs"):
        c.run(execute=lambda: c.execute().model_copy(update=changes[field]))
    assert not c.index.results


@pytest.mark.parametrize("remove_protocol", (False, True))
def test_missing_execution_closure_is_rejected_before_empty_action_return(
    tmp_path, remove_protocol
):
    c = case(tmp_path)
    original = issuer(c, c.run())
    changes = {"execution_evidence": ()}
    if remove_protocol:
        changes["identity_protocol"] = None
    altered = original.model_copy(
        update={"report": original.report.model_copy(update=changes)}
    )
    with pytest.raises(SnapshotError, match="normalized report differs"):
        require_parser_action_evidence(
            altered, artifacts=c.artifacts, delivery_revision="d" * 40
        )


@pytest.mark.parametrize("strip_fields", (False, True))
def test_v1_cannot_be_used_to_downgrade_computational_evidence(tmp_path, strip_fields):
    c = case(tmp_path)
    original = issuer(c, c.run())
    report = original.report
    if strip_fields:
        report = report.model_copy(
            update={"execution_evidence": (), "identity_protocol": None}
        )
    with pytest.raises(ValueError, match="v1 original cannot contain"):
        evaluate_original_issuer(
            report,
            source=original.source,
            decision_at=original.decision_at,
            policy_version="original-issuer-operating-v1",
        )


def test_v3_owner_resource_keys_survive_relocation_and_detect_changed_bytes(
    tmp_path, monkeypatch
):
    from fundamental_service.dqc_rulesets import (
        DqcRulesetCatalogV1,
        DqcRulesetBindingV1,
    )
    from fundamental_service.serialization import sha256_digest
    import hashlib

    c = case(tmp_path / "case")
    build = ParserBuildIdentityV1(
        implementation_digest="1" * 64,
        runtime_digest="2" * 64,
        output_schema_digest="3" * 64,
    )
    monkeypatch.setattr(ParserBuildChecks, "current", lambda self: build)
    inputs = []
    for name in ("mount-a", "mount-b"):
        root = tmp_path / name
        for directory in ("taxonomy", "edgar", "xule", "filing"):
            (root / directory).mkdir(parents=True)
            (root / directory / "content").write_bytes(b"fixed bytes")
        (root / "rules.zip").write_bytes(b"fixed rules")
        catalog = DqcRulesetCatalogV1(
            bindings=(
                DqcRulesetBindingV1(
                    taxonomy_namespace="http://fasb.org/us-gaap/2025",
                    path=root / "rules.zip",
                    sha256=hashlib.sha256(b"fixed rules").hexdigest(),
                ),
            )
        )
        profile = c.profile.model_copy(
            update={
                "edgar_plugin_dir": root / "edgar",
                "xule_plugin_dir": root / "xule",
                "dqc_ruleset_path": root / "rules.zip",
                "dqc_ruleset_catalog": catalog,
            }
        )
        arguments = dict(
            representation="normalized",
            delivery_revision="d" * 40,
            normalization_inputs=("2" * 64,),
            profile=profile,
            taxonomy_version="2025",
            taxonomy_cache_dir=root / "taxonomy",
            source_content_hash=hashlib.sha256(b"fixed bytes").hexdigest(),
            build_checks=ParserBuildChecks(),
        )
        inputs.append(
            (
                parser_action_input(root / "filing" / "content", **arguments),
                arguments,
                root,
            )
        )
    first, second = inputs[0][0], inputs[1][0]
    assert isinstance(first, ParserActionInputV3)
    assert first == second and first.digest == second.digest
    assert all(not Path(name).is_absolute() for name, _ in first.resources)
    request, arguments, root = inputs[1]
    (root / "rules.zip").write_bytes(b"changed rules")
    changed = parser_action_input(root / "filing" / "content", **arguments)
    assert changed.digest != request.digest
    assert sha256_digest(changed.resources) != sha256_digest(request.resources)


@pytest.mark.parametrize(
    "offset,report_digest,evidence_digest",
    (
        (
            0,
            "3c40005946280f835c8fafc341b1344def863f91c22ba2d5484cc905b225939a",
            "39485b63781efc5c9c2a0beb49b6686a7b546a205920e6bc9d63ffdb8968d579",
        ),
        (
            8,
            "ef557b3b6c87681d680e1a611226dda7455bbb180e1f5ed9cc039cfc3317c4cd",
            "be91d60e9131a981a2409fd48244121fd64b2745004dce097f7b4d80fea521b6",
        ),
    ),
)
def test_v1_retained_bytes_preserve_pre_split_digest(
    offset, report_digest, evidence_digest
):
    from datetime import timezone, timedelta
    from fundamental_service.serialization import sha256_digest
    from test_original_issuer import original, DECISION

    # Captured from c2077b8b's unmodified source package, including its legacy
    # offset-sensitive report JSON; the new policy does not redefine old proof.
    report, source = original()
    zone = timezone(timedelta(hours=offset))
    source = source.model_copy(
        update={
            "captured_at": source.captured_at.astimezone(zone),
            "available_at": source.available_at.astimezone(zone),
        }
    )
    evidence = evaluate_original_issuer(
        report,
        source=source,
        decision_at=DECISION,
        policy_version="original-issuer-operating-v1",
    )
    assert sha256_digest(evidence.report.model_dump(mode="json")) == report_digest
    assert sha256_digest(evidence) == evidence_digest


def test_unknown_computation_marker_cannot_be_admitted_as_plain_fallback(tmp_path):
    c = case(tmp_path)
    original = issuer(c, c.run())
    report = original.report.model_copy(
        update={
            "execution_evidence": (),
            "validation_evidence": ("sec-parser-computation-v99:forged",),
        }
    )
    with pytest.raises(ValueError, match="computation representation differs"):
        evaluate_original_issuer(
            report, source=original.source, decision_at=original.decision_at
        )


def test_ingestion_consumes_the_exact_report_admitted_by_automatic_mapping(
    tmp_path, monkeypatch
):
    import fundamental_service.ingestion as ingestion
    import fundamental_service.parser_actions as actions
    from fundamental_service.parser_actions import ParserActions
    from test_parser_actions import Index
    from test_automatic_source_acquisition import acquisition_case, acquire

    request, use_case, state, metadata, artifacts = acquisition_case(
        tmp_path / "acquisition", monkeypatch
    )
    prototype = case(tmp_path / "action")

    def identity(path, **kwargs):
        return prototype.request.model_copy(
            update={
                "delivery_revision": kwargs["delivery_revision"],
                "representation": kwargs["representation"],
                "source_content_hash": kwargs["source_content_hash"],
                "files": ((path.name, kwargs["source_content_hash"]),),
                "entrypoint": path.name,
                "profile_digest": kwargs["profile"].digest(),
                "taxonomy_version": kwargs["taxonomy_version"],
                "resources": (("taxonomy", use_case.settings.taxonomy_cache_sha256),),
            }
        )

    monkeypatch.setattr(actions, "parser_action_input", identity)
    monkeypatch.setattr(actions, "parse_filing_offline", ingestion.parse_filing_offline)
    index = Index()
    use_case.ingestion.parser_actions = ParserActions(index=index, artifacts=artifacts)
    result = acquire(request, use_case)
    assert (
        result.snapshot_id and result.canonical_fact_ids and result.mapping_evidence_ref
    )
    assert index.results
    assert "MAPPING_REPORT_MISMATCH" not in result.issue_codes
    assert metadata.mappings
    before = (
        len(metadata.facts),
        len(metadata.mappings),
        len(metadata.snapshots),
        len(metadata.acquisitions),
    )
    repeated = acquire(request, use_case)
    assert repeated.reused
    assert (
        repeated.model_copy(update={"status": result.status, "reused": result.reused})
        == result
    )
    assert before == (
        len(metadata.facts),
        len(metadata.mappings),
        len(metadata.snapshots),
        len(metadata.acquisitions),
    )
