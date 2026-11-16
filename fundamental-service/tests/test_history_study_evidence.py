"""Research exports verify official arithmetic without promoting scenarios."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from fundamental_service.operating_label_contracts import OperatingComparisonRequestV1
from fundamental_service.operating_labels import replay_operating_comparison
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_operating_labels import comparison_request
from test_operating_scenarios import request as decision_request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_history_study as analysis  # noqa: E402
import export_history_study_evidence as exporter  # noqa: E402


def write_entry(directory: Path, request: OperatingComparisonRequestV1):
    values = {
        "request": request,
        "forecast": replay_operating_scenarios(request.decision),
        "comparison": replay_operating_comparison(request),
    }
    references = {}
    for name, value in values.items():
        raw = canonical_bytes(value)
        path = directory / f"{sha256_digest(value)}.artifact"
        path.write_bytes(raw)
        references[name] = {"path": path.name, "sha256": sha256_digest(value)}
    return exporter.EvidenceEntry.model_validate(references)


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    request = comparison_request()
    origin = json.loads(canonical_bytes(request.decision.source.valuation_timestamp))
    decisions = [
        {
            "issuer_id": f"CIK:{i:010d}",
            "decision_at": origin,
            "decision_accession": request.decision.source.originals[
                -1
            ].source.accession_number,
            "label_accession": request.label.source.originals[0].source.accession_number
            if i <= 91
            else None,
            "label_horizon_matches_forecast": i <= 90,
        }
        for i in range(1, 101)
    ]
    manifest = {"issuer_decisions": decisions}
    manifest_digest = sha256_digest(manifest)
    monkeypatch.setattr(exporter, "MANIFEST_DIGEST", manifest_digest)
    monkeypatch.setattr(analysis, "MANIFEST_DIGEST", manifest_digest)
    index = exporter.EvidenceIndex(
        schema_version="history-study-evidence-index.v1",
        fixed_manifest_digest=manifest_digest,
        runtime=exporter.runtime_pins(),
        entries=(write_entry(tmp_path, request),),
    )
    return manifest, index, tmp_path, request


def replace_file(index, directory, kind, mutate):
    entry = index.entries[0]
    reference = getattr(entry, kind)
    path = directory / reference.path
    value = json.loads(path.read_bytes())
    mutate(value)
    path.write_bytes(canonical_bytes(value))
    return index.model_copy(
        update={
            "entries": (
                entry.model_copy(
                    update={
                        kind: reference.model_copy(
                            update={"sha256": sha256_digest(value)}
                        )
                    }
                ),
            )
        }
    )


def test_recomputed_scenarios_retain_all_cases_and_do_not_invent_exact_losses(evidence):
    manifest, index, directory, request = evidence
    before = {p.name: p.stat().st_mtime_ns for p in directory.iterdir()}
    result = exporter.export_evidence(manifest, index, directory)
    assert {p.name: p.stat().st_mtime_ns for p in directory.iterdir()} == before
    appendix = result["conditional_evidence"]
    assert len(appendix) == 1
    assert result["schema_version"] == "history-study-evidence-export.v2"
    assert appendix[0]["artifact_digests"] == index.entries[0].identity()
    comparison = json.loads(
        exporter.read_evidence(index.entries[0].comparison, directory)
    )
    assert comparison == json.loads(
        canonical_bytes(replay_operating_comparison(request))
    )
    assert len(comparison["comparisons"]) == 4
    assert json.loads(
        exporter.read_evidence(index.entries[0].request, directory)
    ) == json.loads(canonical_bytes(request))
    cases = analysis.decode_panel(result["loss_panel"], manifest)
    assert len(cases) == 100 and sum(len(c.observations) for c in cases) == 1200
    assert all(not row.exact for case in cases for row in case.observations)
    first = cases[0]
    transition = next(
        row
        for row in first.observations
        if row.model == "transition_fcff_dcf"
        and row.years == 3
        and row.target == "next_annual_undiscounted_fcff"
    )
    assert "TRANSITION_EVIDENCE_MISSING" in transition.reasons
    assert transition.label_kind == "conditional_scenario"
    assert all(
        "HISTORY_WINDOW_EVIDENCE_MISSING" in row.reasons
        for row in first.observations
        if row.years > 3
    )
    assert "FROZEN_FIRST_ORIGINAL_LABEL_MISSING" in cases[-1].frozen_reasons
    assert "FROZEN_LABEL_HORIZON_MISMATCH" in cases[90].frozen_reasons
    assert result["complete_exact_study_cases"] == 0
    assert result["independent_conditional_issuers"] == 1
    assert result["supported_history_threshold"] is None
    assert [arm["conditional_comparisons"] for arm in result["arm_summaries"]] == [2, 0]


@pytest.mark.parametrize("kind", ["request", "forecast", "comparison"])
def test_raw_content_tampering_is_rejected(evidence, kind):
    manifest, index, directory, _ = evidence
    path = directory / getattr(index.entries[0], kind).path
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(exporter.DesignError, match="content digest"):
        exporter.export_evidence(manifest, index, directory)


@pytest.mark.parametrize("kind", ["forecast", "comparison"])
def test_rehashed_output_claims_cannot_replace_official_results(evidence, kind):
    manifest, index, directory, _ = evidence
    index = replace_file(
        index, directory, kind, lambda value: value.update(output_digest="f" * 64)
    )
    with pytest.raises(exporter.DesignError, match="official Fundamental replay"):
        exporter.export_evidence(manifest, index, directory)


def test_rehashed_declared_loss_is_not_trusted(evidence):
    manifest, index, directory, _ = evidence

    def fabricated(value):
        value["comparisons"][0]["signed_error"] = "123456"
        value["output_digest"] = sha256_digest(
            {key: item for key, item in value.items() if key != "output_digest"}
        )

    index = replace_file(index, directory, "comparison", fabricated)
    with pytest.raises(exporter.DesignError, match="official Fundamental replay"):
        exporter.export_evidence(manifest, index, directory)


@pytest.mark.parametrize("fault", ["issuer", "date", "label", "model"])
def test_request_substitutions_fail_before_output_can_be_used(evidence, fault):
    manifest, index, directory, _ = evidence

    def substitute(value):
        if fault == "issuer":
            value["decision"]["source"]["identity"]["issuer_id"] = "9999999999"
        elif fault == "date":
            value["decision"]["source"]["valuation_timestamp"] = "2028-01-01T00:00:00Z"
        elif fault == "label":
            value["label"]["source"]["originals"][0]["source"]["accession_number"] = (
                "0000000001-27-999999"
            )
        elif fault == "model":
            value["decision"]["model_versions"]["fcff_dcf"] = "unimplemented-v999"
        value["decision_input_digest"] = sha256_digest(value["decision"])

    index = replace_file(index, directory, "request", substitute)
    with pytest.raises(ValueError):
        exporter.export_evidence(manifest, index, directory)


def test_origin_accession_binding_is_checked_in_addition_to_date(evidence, monkeypatch):
    manifest, index, directory, _ = evidence
    manifest["issuer_decisions"][0]["decision_accession"] = "wrong"
    manifest_digest = sha256_digest(manifest)
    monkeypatch.setattr(exporter, "MANIFEST_DIGEST", manifest_digest)
    monkeypatch.setattr(analysis, "MANIFEST_DIGEST", manifest_digest)
    index = index.model_copy(update={"fixed_manifest_digest": manifest_digest})
    with pytest.raises(exporter.DesignError, match="decision accession"):
        exporter.export_evidence(manifest, index, directory)


def test_missing_artifacts_never_trigger_acquisition(evidence, monkeypatch):
    manifest, index, directory, _ = evidence
    (directory / index.entries[0].forecast.path).unlink()
    monkeypatch.setattr(
        "socket.socket", lambda *a, **k: pytest.fail("offline export used network")
    )
    with pytest.raises(FileNotFoundError):
        exporter.export_evidence(manifest, index, directory)


def test_runtime_and_duplicate_arms_fail_closed(evidence):
    manifest, index, directory, _ = evidence
    invalid = index.model_copy(
        update={"runtime": index.runtime.model_copy(update={"python": "0.0.0"})}
    )
    with pytest.raises(exporter.DesignError, match="runtime"):
        exporter.export_evidence(manifest, invalid, directory)
    invalid = index.model_copy(update={"entries": index.entries * 2})
    with pytest.raises(exporter.DesignError, match="duplicate frozen request"):
        exporter.export_evidence(manifest, invalid, directory)


def test_different_requests_cannot_duplicate_an_issuer_arm(evidence):
    manifest, index, directory, request = evidence
    other = write_entry(
        directory, request.model_copy(update={"protocol_version": "other-protocol"})
    )
    index = index.model_copy(update={"entries": (*index.entries, other)})
    with pytest.raises(exporter.DesignError, match="duplicate issuer/history arm"):
        exporter.export_evidence(manifest, index, directory)


def fourth_arm(request, *, change_basis=False):
    decision = request.decision
    first = decision.periods[0]
    older = first.model_copy(
        update={
            "fiscal_year": first.fiscal_year - 1,
            "period_start": first.period_start.replace(year=first.fiscal_year - 1),
            "period_end": first.period_end.replace(year=first.fiscal_year - 1),
        }
    )
    # The extra year deliberately refers to unavailable facts. Formal replay must
    # abstain; an arm's declared length is never proof of usable history.
    scenarios = tuple(
        scenario.model_copy(
            update={
                "continuing_capex_fractions": {
                    **scenario.continuing_capex_fractions,
                    older.fiscal_year: Decimal(1),
                }
            }
        )
        for scenario in decision.scenarios
    )
    decision = decision.model_copy(
        update={"periods": (older, *decision.periods), "scenarios": scenarios}
    )
    request = request.model_copy(
        update={
            "decision": decision,
            "decision_input_digest": sha256_digest(decision),
            **(
                {"protocol_version": "changed-comparison-basis"} if change_basis else {}
            ),
        }
    )
    return OperatingComparisonRequestV1.model_validate_json(canonical_bytes(request))


def test_history_arm_shortage_retains_official_refusal(evidence):
    manifest, index, directory, request = evidence
    other = write_entry(directory, fourth_arm(request))
    index = index.model_copy(update={"entries": (*index.entries, other)})
    result = exporter.export_evidence(manifest, index, directory)
    arms = [row for row in result["arm_summaries"] if row["years"] == 4]
    assert len(arms) == 2 and all(row["conditional_comparisons"] == 0 for row in arms)
    assert all(row["abstained_comparisons"] == 2 for row in arms)
    assert result["independent_conditional_issuers"] == 1
    assert result["complete_exact_study_cases"] == 0


def test_history_arms_cannot_change_comparison_basis(evidence):
    manifest, index, directory, request = evidence
    other = write_entry(directory, fourth_arm(request, change_basis=True))
    index = index.model_copy(update={"entries": (*index.entries, other)})
    with pytest.raises(exporter.DesignError, match="comparison basis"):
        exporter.export_evidence(manifest, index, directory)


def test_official_source_conflicts_stay_abstained_and_do_not_count_as_success(evidence):
    manifest, index, directory, request = evidence
    decision = decision_request(second_revenue="999")
    request = request.model_copy(
        update={"decision": decision, "decision_input_digest": sha256_digest(decision)}
    )
    index = index.model_copy(update={"entries": (write_entry(directory, request),)})
    result = exporter.export_evidence(manifest, index, directory)
    assert result["represented_issuers"] == 1
    assert result["independent_conditional_issuers"] == 0
    assert all(arm["conditional_comparisons"] == 0 for arm in result["arm_summaries"])
    assert all(arm["abstained_comparisons"] == 2 for arm in result["arm_summaries"])
    comparison = json.loads(
        exporter.read_evidence(index.entries[0].comparison, directory)
    )
    assert all(row["signed_error"] is None for row in comparison["comparisons"])


@pytest.mark.parametrize("fault", ["whitespace", "duplicate-field"])
def test_rehashed_noncanonical_or_duplicate_json_cannot_discard_evidence(
    evidence, fault
):
    manifest, index, directory, _ = evidence
    entry = index.entries[0]
    path = directory / entry.request.path
    raw = path.read_bytes()
    raw = (
        raw + b" "
        if fault == "whitespace"
        else b'{"policy_version":"ignored",' + raw[1:]
    )
    path.write_bytes(raw)
    index = index.model_copy(
        update={
            "entries": (
                entry.model_copy(
                    update={
                        "request": entry.request.model_copy(
                            update={"sha256": exporter.digest(raw)}
                        )
                    }
                ),
            )
        }
    )
    with pytest.raises(exporter.DesignError, match="canonical|duplicate JSON"):
        exporter.export_evidence(manifest, index, directory)


def test_relocation_and_republication_preserve_identity_and_artifact(
    evidence, tmp_path
):
    manifest, index, directory, _ = evidence
    result = exporter.export_evidence(manifest, index, directory)
    absolute = index.model_copy(
        update={
            "entries": tuple(
                exporter.EvidenceEntry.model_validate(
                    {
                        kind: {
                            "path": str(directory / getattr(entry, kind).path),
                            "sha256": getattr(entry, kind).sha256,
                        }
                        for kind in ("request", "forecast", "comparison")
                    }
                )
                for entry in index.entries
            )
        }
    )
    assert canonical_bytes(exporter.export_evidence(manifest, absolute, directory)) == (
        canonical_bytes(result)
    )
    output = tmp_path / "published"
    first = exporter.publish_report(output, result)
    before = {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.glob("*.json")
    }
    second = exporter.publish_report(output, result)
    assert first["wrote"] and not second["wrote"]
    assert first["report_digest"] == second["report_digest"]
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.glob("*.json")
    }


def test_cli_reads_strict_json_arrays_and_publishes_a_reusable_analysis_panel(
    evidence, monkeypatch, capsys
):
    manifest, index, directory, _ = evidence
    manifest_path, index_path = directory / "manifest.json", directory / "index.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    index_path.write_bytes(canonical_bytes(index))
    output = directory / "cli-output"
    monkeypatch.setattr(
        exporter.subprocess,
        "check_output",
        lambda command, **kwargs: "test-commit" if "rev-parse" in command else "",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_history_study_evidence.py",
            "--manifest",
            str(manifest_path),
            "--evidence-index",
            str(index_path),
            "--exact-commit",
            "test-commit",
            "--output-directory",
            str(output),
        ],
    )
    assert exporter.main() == 0
    first = json.loads(capsys.readouterr().out)
    assert first["wrote"] is True
    panel = json.loads((output / f"{first['loss_panel_digest']}.json").read_bytes())
    assert len(analysis.decode_panel(panel, manifest)) == 100
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()}
    assert exporter.main() == 0
    second = json.loads(capsys.readouterr().out)
    assert second["wrote"] is False
    assert all(not row["wrote"] for row in second["publications"].values())
    assert second["input_digest"] == first["input_digest"]
    assert second["output_digest"] == first["output_digest"]
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()
    }
