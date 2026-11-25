from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import os
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from time import monotonic
from zipfile import ZipFile

import pytest
from fundamental_service.arelle_parser import ArelleFindingV1, fact_semantic_digest
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_candidate_contracts import FiscalSourceUseScopeV1
from fundamental_service.fiscal_classification_review import verify_fiscal_source_review
from fundamental_service.fiscal_classification_source import FiscalClassificationSource
from fundamental_service.fiscal_discovery import FiscalDiscoveryEvidenceV1
from fundamental_service.fiscal_focus_witness import (
    SignedFiscalDiagnosticFocusWitnessV1,
)
from fundamental_service.fiscal_source_accounting_policy import (
    AccountingRefusal,
    AccountingSupport,
    _read_disclosures,
    _Refusal,
    evaluate_source_accounting,
    source_accounting_policy_identity,
)
from fundamental_service.fiscal_source_accounting_policy_contracts import (
    AccountingReplayRecordV3,
    encode_accounting_record,
    read_accounting_record,
)
from fundamental_service.fiscal_source_contracts import evaluate_fiscal_issuer
from fundamental_service.fiscal_statement_mapping import (
    fiscal_display_profile_digest,
    fiscal_mapping_policy_digest,
    map_fiscal_primary_source,
)
from fundamental_service.fiscal_statement_registry import (
    fiscal_primary_scopes,
    fiscal_statement_registry,
    selected_fiscal_coverage,
)
from fundamental_service.fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationCompleteRefusedV1,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from lxml import etree
from pydantic import TypeAdapter, ValidationError

_ARCHIVE = "c2633b021dcd9f36160b732de59abf30dbe16fa234de8e92dc7583f312e5b5a5"
_PRIMARY = "3b63f34ecf33818dde9b8cfcdbc9074399e4578e1b971a7832dbc5d9883cf501"
_REVISION = "5753be993a8162a49c741739d06507119e0be6f4"
_MEMBER = "msft-20240930.htm"
_SOURCE_HASHES = {
    "historical": "acdf22b16e9dbd10266354ab29c21c423362ec895e0a47ccd8a721ab691ca2b2",
    "current": "d0df57b451373c40afc2bace33e2d9a39d3dd7aac24ef9ea33d8d5eed17052db",
}


def _deadline() -> float:
    return 60.0


def _ref(identity: str, value: object, role: str) -> ArtifactRefV1:
    return ArtifactRefV1(
        artifact_id=identity,
        content_hash=hashlib.sha256(canonical_bytes(value)).hexdigest(),
        media_type="application/json",
        role=role,
    )


@pytest.fixture(scope="module")
def sources() -> dict[str, FiscalClassificationSource]:
    configured = os.getenv("ISSUE495_RETAINED_EVIDENCE_ROOT")
    if not configured:
        pytest.skip(
            "Set ISSUE495_RETAINED_EVIDENCE_ROOT for original SEC accounting-policy checks"
        )
    root = Path(configured)
    archive_path = root / "sources-worker/content" / _ARCHIVE[:2] / (_ARCHIVE + ".bin")
    if not archive_path.is_file():
        pytest.skip("Retained original SEC archive is not installed")
    archive = archive_path.read_bytes()
    assert hashlib.sha256(archive).hexdigest() == _ARCHIVE
    result = {}
    for case in ("historical", "current"):
        directory = root / "formal-fiscal-sources" / _REVISION / ("msft-" + case)
        source_path = directory / "0000950170-24-118967-1.stdout.json"
        witness_path = directory / "witness-read-1.stdout.json"
        discovery_path = directory / "discover-1.stdout.json"
        if any(
            not path.is_file() for path in (source_path, witness_path, discovery_path)
        ):
            pytest.skip(
                "Exact retained source, witness and discovery files are not installed"
            )
        source = FiscalOriginalValidationEvidenceV1.model_validate_json(
            json.dumps(json.loads(source_path.read_bytes())["evidence"])
        )
        witness = SignedFiscalDiagnosticFocusWitnessV1.model_validate_json(
            json.dumps(json.loads(witness_path.read_bytes())["evidence"])
        )
        discovery = FiscalDiscoveryEvidenceV1.model_validate_json(
            json.dumps(json.loads(discovery_path.read_bytes())["evidence"])
        )
        assert sha256_digest(source.model_dump(mode="json")) == _SOURCE_HASHES[case]
        outcome = source.outcome
        assert isinstance(outcome, FiscalValidationCompleteRefusedV1)
        source_ref = _ref(
            source.artifact_id,
            source.model_dump(mode="json"),
            "fiscal-original-validation",
        )
        witness_ref = _ref(
            witness.artifact_id, witness, "fiscal-diagnostic-focus-witness-v1"
        )
        reviewed = next(
            item
            for item in fiscal_primary_scopes(fiscal_statement_registry())
            if item.accession_number == source.request.filing.accession_number
        )
        policy = fiscal_mapping_policy_digest()
        batch = map_fiscal_primary_source(
            source,
            source_ref,
            archive=archive,
            reviewed=reviewed,
            target_periods=tuple(
                item.period for item in selected_fiscal_coverage(discovery).quarters
            ),
            security_id="MSFT",
            policy_digest=policy,
            check_deadline=_deadline,
        )
        scope = FiscalSourceUseScopeV1(
            source_validation_ref=source_ref,
            validation_kind="complete_refused",
            source_binding_digest=batch.source_binding_digest,
            issuer_id=source.request.filing.cik,
            accession_number=source.request.filing.accession_number,
            cutoff_at=source.request.valuation_timestamp,
            runtime=outcome.runtime,
            raw_report_digest=sha256_digest(
                outcome.claim.report.model_dump(mode="json")
            ),
            parser_action_refs=outcome.action_refs,
            witness_ref=witness_ref,
            display_profile_digest=fiscal_display_profile_digest(),
            mapping_policy_digest=policy,
            permitted_inputs=batch.observations,
        )
        result[case] = FiscalClassificationSource(scope, source, witness, archive)
    return result


def _original(source: FiscalClassificationSource) -> bytes:
    with ZipFile(BytesIO(source.archive)) as archive:
        return archive.read(_MEMBER)


def _root(source: FiscalClassificationSource) -> etree._Element:
    return etree.fromstring(
        _original(source), etree.XMLParser(no_network=True, resolve_entities=False)
    )


def _text(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _table(root: etree._Element, label: str) -> etree._Element:
    matches = [
        t
        for t in root.xpath('//*[local-name()="table"]')
        if any(
            len(row) and _text(row[0]) == label
            for row in t.xpath('.//*[local-name()="tr"]')
        )
    ]
    if label == "Derivatives, net (a)":
        matches = [
            t
            for t in matches
            if any(_text(row[0]) == "September 30, 2024" for row in t if len(row))
        ]
    assert len(matches) == 1
    return matches[0]


def _row(table: etree._Element, label: str) -> etree._Element:
    rows = [row for row in table if len(row) and _text(row[0]) == label]
    assert len(rows) == 1
    return rows[0]


def _rename(node: etree._Element, old: str, new: str) -> None:
    matches = [
        n
        for n in node.iter()
        if old in _text(n) and not any(old in _text(child) for child in n)
    ]
    assert len(matches) == 1
    target = matches[0]
    text = _text(target).replace(old, new)
    for child in tuple(target):
        target.remove(child)
    target.text = text


def _mutate(root: etree._Element, mutation: str) -> None:
    investment = _table(root, "Derivatives, net (a)")
    derivative = _table(root, "Gross amounts of derivatives")
    focus_row = _row(investment, "Derivatives, net (a)")
    focus = focus_row.xpath('.//*[local-name()="nonFraction"]')[2]
    location = _row(derivative, "Short-term investments")
    if mutation == "row":
        _rename(focus_row[0], "Derivatives, net (a)", "Cash settlement (a)")
    elif mutation == "column":
        _rename(investment, "Short-term Investments", "Long-term Investments")
    elif mutation == "date":
        _rename(investment, "September 30, 2024", "June 30, 2024")
    elif mutation == "heading":
        heading = next(
            p
            for p in root.xpath('//*[local-name()="p"]')
            if _text(p) == "NOTE 5 — DERIVATIVES"
        )
        _rename(heading, "NOTE 5", "NOTE 15")
    elif mutation == "title":
        title = next(
            p
            for p in root.xpath('//*[local-name()="p"]')
            if _text(p) == "Fair Values of Derivative Instruments"
        )
        _rename(title, "Fair Values", "Notional Values")
    elif mutation == "missing_note5":
        derivative.getparent().remove(derivative)
    elif mutation == "crossreference":
        footnote = root.xpath('//*[local-name()="footnote"]')[0]
        _rename(footnote, "Note 5", "Note 6")
    elif mutation == "footnote_label":
        footnote = root.xpath('//*[local-name()="footnote"]')[0]
        _rename(footnote.getparent().getparent(), "(a)", "(b)")
    elif mutation == "footnote_link":
        relationship = next(
            n
            for n in root.xpath('//*[local-name()="relationship"]')
            if focus.get("id") in n.get("fromRefs", "").split()
        )
        relationship.set("fromRefs", "another-fact")
    elif mutation == "duplicate":
        duplicate = copy.deepcopy(investment)
        for element in duplicate.iter():
            if element.get("id"):
                element.set("id", "duplicate-" + element.get("id"))
        investment.addnext(duplicate)
    elif mutation == "duplicate_cell":
        duplicate = copy.deepcopy(focus)
        duplicate.set("id", "duplicate-" + focus.get("id"))
        focus.getparent().append(duplicate)
    elif mutation == "omitted_zero":
        cash = _row(investment, "Cash")
        cash.getparent().remove(cash)
    elif mutation == "extra_component":
        new_row = copy.deepcopy(_row(investment, "Cash"))
        for n in new_row.xpath(".//*[@id]"):
            n.set("id", "extra-" + n.get("id"))
        _rename(new_row[0], "Cash", "Unexplained asset class")
        investment.append(new_row)
    elif mutation == "equivalent_location":
        _rename(location[0], "Short-term investments", "Long-term investments")
    elif mutation == "equivalent_zero_substitution":
        _rename(_row(investment, "Cash")[0], "Cash", "Receivables")
    elif mutation == "sign":
        focus.attrib.pop("sign")
    elif mutation == "display_sign":
        cell = next(
            n for n in focus.iterancestors() if etree.QName(n).localname == "td"
        )
        _rename(cell, "(", "")
    elif mutation == "offset_sign":
        _row(
            derivative, "Gross amounts of derivatives offset in the balance sheets"
        ).xpath('.//*[local-name()="nonFraction"]')[0].set("sign", "-")
    elif mutation == "context_date":
        context = root.xpath("//*[@id=$identity]", identity=focus.get("contextRef"))[0]
        context.xpath('.//*[local-name()="instant"]')[0].text = "2024-06-30"
    elif mutation == "dimension":
        context = root.xpath("//*[@id=$identity]", identity=focus.get("contextRef"))[0]
        context.xpath('.//*[local-name()="explicitMember"]')[
            0
        ].text = "us-gaap:CashMember"
    elif mutation == "concept_namespace":
        focus.set("name", "msft:ShortTermInvestments")
    elif mutation == "unit":
        unit = root.xpath("//*[@id=$identity]", identity=focus.get("unitRef"))[0]
        unit.xpath('.//*[local-name()="measure"]')[0].text = "iso4217:EUR"
    elif mutation == "scale_overflow":
        focus.set("scale", "1001")
    elif mutation == "decimals_overflow":
        focus.set("decimals", "-1001")
    elif mutation == "numeric_overflow":
        focus.text = "1" * 1001
    elif mutation == "logical_column":
        focus_row[0].set("colspan", "2")
    elif mutation == "swapped_date_columns":
        date_row = next(row for row in derivative if "September 30, 2024" in _text(row))
        date_row[2].set("colspan", "2")
    else:
        raise AssertionError(mutation)


@pytest.mark.parametrize("case", ("historical", "current"))
def test_retained_original_produces_limited_opinion_and_all_five_whole_bridges(
    sources, case
):
    source = sources[case]
    before = canonical_bytes(source.evidence.model_dump(mode="json"))
    witness_before = canonical_bytes(source.witness)
    live = evaluate_source_accounting(source, check_deadline=_deadline)
    result = live.result
    review = live.review()
    assert review is not None
    assert isinstance(result, AccountingSupport)
    assert result.scope_sha256 == source.scope.scope_digest
    assert result.archive_sha256 == _ARCHIVE
    assert result.primary_sha256 == _PRIMARY
    assert result.source_evidence_sha256 == _SOURCE_HASHES[case]
    assert result.policy == source_accounting_policy_identity()
    assert review.opinion == "source-as-disclosed"
    assert review.tagging == "unresolved"
    assert len(review.facts) == 16
    facts = {f.fact_id: f for f in review.facts}
    by_role = {f.role: facts[f.transcription.fact_id] for f in result.tagged}
    assert {role: fact.value for role, fact in by_role.items()} == {
        "investment_debt": Decimal("57589000000"),
        "investment_equity": Decimal("0"),
        "investment_cash": Decimal("0"),
        "investment_derivative": Decimal("-1000000"),
        "investment_total": Decimal("57588000000"),
        "balance_cash": Decimal("20840000000"),
        "balance_investments": Decimal("57588000000"),
        "balance_combined": Decimal("78428000000"),
        "derivative_gross": Decimal("318000000"),
        "derivative_offset": Decimal("196000000"),
        "derivative_collateral": Decimal("0"),
        "derivative_net": Decimal("122000000"),
        "derivative_short_term": Decimal("-1000000"),
        "derivative_current": Decimal("118000000"),
        "derivative_noncurrent": Decimal("5000000"),
        "derivative_location_total": Decimal("122000000"),
    }
    assert [bridge.residual for bridge in review.reconciliations] == [Decimal(0)] * 5
    assert [bridge.precision_allowance for bridge in review.reconciliations] == [
        Decimal("2500000"),
        Decimal("1000000"),
        Decimal("1500000"),
        Decimal("2000000"),
        Decimal("2000000"),
    ]
    assert [term.coefficient for term in review.reconciliations[3].terms] == [
        1,
        -1,
        1,
    ]
    assert by_role["derivative_offset"].raw_sign is None
    assert by_role["investment_derivative"].raw_sign == "-"
    assert (
        by_role["investment_derivative"].fact.dimensions
        != by_role["derivative_short_term"].fact.dimensions
    )
    assert len(result.explanations()) == 6
    assert len(result.tables) == 3
    assert all(
        predicate.supports and predicate.falsified_by
        for predicate in result.explanations()
    )
    assert result.link.footnote.text.startswith("Refer to Note 5")
    assert [
        (
            item.row_label.text,
            item.date_header.text,
            item.column_header.text,
            item.logical_column,
            item.cell.text,
        )
        for item in result.plain_zeros
    ] == [
        (row, "September 30, 2024", "Derivative Assets", 3, "0")
        for row in ("Other current liabilities", "Other long-term liabilities")
    ]
    root = _root(source)
    for item in result.plain_zeros:
        (cell,) = root.xpath(
            item.cell.xpath, namespaces={k: v for k, v in root.nsmap.items() if k}
        )
        assert cell.sourceline == item.cell.source_line
        assert (
            hashlib.sha256(etree.tostring(cell, method="c14n")).hexdigest()
            == item.cell.sha256
        )
        assert not cell.xpath('.//*[local-name()="nonFraction"]')
    assert canonical_bytes(source.evidence.model_dump(mode="json")) == before
    assert canonical_bytes(source.witness) == witness_before
    outcome = source.evidence.outcome
    assert outcome.kind == "complete_refused"
    assert outcome.integrity.quality_decision == "block"
    assert outcome.claim.report.blocking_finding_codes() == ("DQC.US.0015.5970",)
    assert source.witness.witness.raw_finding.rule_severity == "error"
    assert source.witness.witness.raw_finding.severity == "warning"
    raw = encode_accounting_record(live, check_deadline=_deadline)
    adapter = TypeAdapter(AccountingReplayRecordV3)
    embedded = read_accounting_record(raw, check_deadline=_deadline)
    for _ in range(2):
        embedded = adapter.validate_json(embedded.model_dump_json(), strict=True)
        assert embedded.result == result
        assert embedded.review() == review
    verify_fiscal_source_review(source, review, check_deadline=_deadline)


def test_cutoff_scopes_remain_distinct(sources):
    historical = evaluate_source_accounting(
        sources["historical"], check_deadline=_deadline
    )
    current = evaluate_source_accounting(sources["current"], check_deadline=_deadline)
    assert historical.result.scope_sha256 != current.result.scope_sha256
    assert (
        historical.review().scope.source_validation_ref
        != current.review().scope.source_validation_ref
    )
    assert historical.review().scope.witness_ref != current.review().scope.witness_ref
    assert historical.review().scope.cutoff_at != current.review().scope.cutoff_at
    assert historical.result.archive_sha256 == current.result.archive_sha256


@pytest.mark.parametrize(
    "mutation",
    (
        "row",
        "column",
        "date",
        "heading",
        "title",
        "missing_note5",
        "crossreference",
        "footnote_label",
        "footnote_link",
        "duplicate",
        "duplicate_cell",
        "omitted_zero",
        "extra_component",
        "equivalent_location",
        "equivalent_zero_substitution",
        "sign",
        "display_sign",
        "offset_sign",
        "context_date",
        "dimension",
        "concept_namespace",
        "unit",
        "scale_overflow",
        "decimals_overflow",
        "numeric_overflow",
        "logical_column",
        "swapped_date_columns",
    ),
)
def test_semantic_mutations_refuse_below_the_original_fingerprint_gate(
    sources, mutation
):
    source = sources["historical"]
    root = _root(source)
    _mutate(root, mutation)
    altered = etree.tostring(root)
    assert hashlib.sha256(altered).hexdigest() != _PRIMARY
    if mutation in {"scale_overflow", "decimals_overflow", "numeric_overflow"}:
        with pytest.raises(SnapshotError) as error:
            _read_disclosures(source, altered, check_deadline=_deadline)
        assert error.value.code == "FISCAL_ACCOUNTING_BUDGET_EXCEEDED"
        return
    with pytest.raises(_Refusal) as refusal:
        _read_disclosures(source, altered, check_deadline=_deadline)
    assert refusal.value.reason != "source_hash_mismatch"
    if mutation in ("duplicate", "duplicate_cell"):
        assert refusal.value.reason == "ambiguous_disclosure"
        assert "duplicate evidence identities" not in refusal.value.detail


def test_whole_path_rejects_altered_original(sources):
    source = sources["historical"]
    root = _root(source)
    _mutate(root, "equivalent_location")
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(_MEMBER, etree.tostring(root))
    result = evaluate_source_accounting(
        replace(source, archive=output.getvalue()), check_deadline=_deadline
    )
    assert isinstance(result.result, AccountingRefusal)
    assert result.result.reason == "source_hash_mismatch"


@pytest.mark.parametrize(
    "field",
    (
        "cutoff_at",
        "source_binding_digest",
        "raw_report_digest",
        "mapping_policy_digest",
        "display_profile_digest",
        "accession_number",
        "issuer_id",
        "runtime",
        "source_validation_ref",
        "witness_ref",
    ),
)
def test_exact_scope_drift_is_named_refusal(sources, field):
    source = sources["historical"]
    replacements = {
        "cutoff_at": sources["current"].scope.cutoff_at,
        "source_binding_digest": "0" * 64,
        "raw_report_digest": "0" * 64,
        "mapping_policy_digest": "0" * 64,
        "display_profile_digest": "0" * 64,
        "accession_number": "0000950170-24-008814",
        "issuer_id": "0000320193",
        "runtime": source.scope.runtime.model_copy(
            update={"validation_profile_digest": "0" * 64}
        ),
        "source_validation_ref": sources["current"].scope.source_validation_ref,
        "witness_ref": sources["current"].scope.witness_ref,
    }
    changed = replace(
        source, scope=source.scope.model_copy(update={field: replacements[field]})
    )
    changed_scope = changed.scope
    changed_scope = changed_scope.model_copy(
        update={
            "permitted_inputs": tuple(
                item.model_copy(
                    update={
                        "issuer_id": changed_scope.issuer_id,
                        "accession_number": changed_scope.accession_number,
                        "source_artifact_id": changed_scope.source_validation_ref.artifact_id,
                        "source_binding_digest": changed_scope.source_binding_digest,
                    }
                )
                for item in changed_scope.permitted_inputs
            )
        }
    )
    changed = replace(
        changed,
        scope=FiscalSourceUseScopeV1.model_validate_json(
            changed_scope.model_dump_json()
        ),
    )
    result = evaluate_source_accounting(changed, check_deadline=_deadline)
    assert isinstance(result.result, AccountingRefusal)
    assert result.result.reason == "source_scope_mismatch"


def test_changed_focus_is_not_selected_by_witness_id(sources):
    source = sources["historical"]
    focus = source.witness.witness.actual_focus.model_copy(
        update={"fact_id": "different-focus"}
    )
    witness = source.witness.model_copy(
        update={
            "witness": source.witness.witness.model_copy(update={"actual_focus": focus})
        }
    )
    changed = replace(source, witness=witness)
    changed = replace(
        changed,
        scope=changed.scope.model_copy(
            update={
                "witness_ref": _ref(
                    witness.artifact_id, witness, "fiscal-diagnostic-focus-witness-v1"
                )
            }
        ),
    )
    result = evaluate_source_accounting(changed, check_deadline=_deadline)
    assert isinstance(result.result, AccountingRefusal)
    assert result.result.reason == "focus_mismatch"


def test_deadline_errors_never_become_accounting_opinions(sources):
    source = sources["historical"]
    calls = 0

    def expire() -> float:
        nonlocal calls
        calls += 1
        if calls == 20:
            raise SnapshotError("DEADLINE_EXCEEDED", "test deadline")
        return 1.0

    with pytest.raises(SnapshotError) as failure:
        evaluate_source_accounting(source, check_deadline=expire)
    assert failure.value.code == "DEADLINE_EXCEEDED"
    assert calls == 20


def test_bounded_work_and_invalid_xml_are_operational_errors(sources):
    source = sources["historical"]
    with pytest.raises(SnapshotError) as archive_budget:
        evaluate_source_accounting(
            replace(source, archive=b"x" * (32 * 1024 * 1024 + 1)),
            check_deadline=_deadline,
        )
    assert archive_budget.value.code == "FISCAL_ACCOUNTING_BUDGET_EXCEEDED"
    for raw in (
        b"x" * (6 * 1024 * 1024 + 1),
        b"<broken",
        b'<!DOCTYPE x [<!ENTITY a "x">]><x>&a;</x>',
    ):
        with pytest.raises(SnapshotError):
            _read_disclosures(source, raw, check_deadline=_deadline)


def test_outcome_is_frozen_and_forbids_extra_approval_fields(sources):
    result = evaluate_source_accounting(sources["historical"], check_deadline=_deadline)
    with pytest.raises(ValidationError):
        result.result.kind = "refused"
    payload = json.loads(encode_accounting_record(result, check_deadline=_deadline))
    payload["approved"] = True
    with pytest.raises(ValidationError):
        TypeAdapter(AccountingReplayRecordV3).validate_json(json.dumps(payload))


def _with_report(source, report):
    outcome = source.evidence.outcome
    original = outcome.claim
    claim = evaluate_fiscal_issuer(
        report,
        filing=original.filing,
        source=original.source,
        decision_at=original.decision_at,
        request_digest=original.request_digest,
    )
    assert claim.status == "refused"
    evidence = FiscalOriginalValidationEvidenceV1.model_validate_json(
        source.evidence.model_copy(
            update={
                "outcome": outcome.model_copy(
                    update={"claim": claim, "issue_codes": claim.issue_codes}
                )
            }
        ).model_dump_json()
    )
    report = evidence.outcome.claim.report
    source_ref = _ref(
        evidence.artifact_id,
        evidence.model_dump(mode="json"),
        "fiscal-original-validation",
    )
    body = source.witness.witness.model_copy(
        update={
            "source_validation_ref": source_ref,
            "raw_report_digest": sha256_digest(report.model_dump(mode="json")),
            "raw_report_fact_digest": fact_semantic_digest(report),
            "raw_report_findings_digest": sha256_digest(
                sorted(report.findings, key=sha256_digest)
            ),
            "raw_finding": next(
                (f for f in report.findings if f.code == "DQC.US.0015.5970"),
                source.witness.witness.raw_finding,
            ),
        }
    )
    witness = SignedFiscalDiagnosticFocusWitnessV1.model_validate_json(
        source.witness.model_copy(update={"witness": body}).model_dump_json()
    )
    scope = source.scope.model_copy(
        update={
            "source_validation_ref": source_ref,
            "source_binding_digest": source_ref.content_hash,
            "raw_report_digest": body.raw_report_digest,
            "witness_ref": _ref(
                witness.artifact_id, witness, "fiscal-diagnostic-focus-witness-v1"
            ),
            "permitted_inputs": tuple(
                item.model_copy(
                    update={"source_binding_digest": source_ref.content_hash}
                )
                for item in source.scope.permitted_inputs
            ),
        }
    )
    return FiscalClassificationSource(
        FiscalSourceUseScopeV1.model_validate_json(scope.model_dump_json()),
        evidence,
        witness,
        source.archive,
    )


@pytest.mark.parametrize(
    "change",
    (
        "additional",
        "critical",
        "fatal",
        "duplicate",
        "inactive",
        "inactive_and_additional",
    ),
)
def test_additional_critical_ambiguous_or_inactive_diagnostic_never_gets_an_opinion(
    sources, change
):
    source = sources["historical"]
    report = source.evidence.outcome.claim.report
    target = source.witness.witness.raw_finding
    if change == "additional":
        findings = (
            *report.findings,
            ArelleFindingV1(
                code="another-blocker",
                severity="error",
                message="Independent blocking diagnostic",
            ),
        )
    elif change == "duplicate":
        findings = (*report.findings, target)
    else:
        altered = target.model_copy(
            update={
                "rule_severity": change
                if change in {"critical", "fatal"}
                else target.rule_severity,
            }
        )
        if change.startswith("inactive"):
            altered = target.model_copy(
                update={"rule_effective_date": date(2099, 1, 1)}
            )
        findings = tuple(altered if f == target else f for f in report.findings)
    if change == "inactive_and_additional":
        findings += (
            ArelleFindingV1(
                code="another-blocker",
                severity="error",
                message="Independent blocking diagnostic",
            ),
        )
    changed_report = report.model_copy(update={"findings": findings})
    if change == "inactive":
        original = source.evidence.outcome.claim
        assert (
            evaluate_fiscal_issuer(
                changed_report,
                filing=original.filing,
                source=original.source,
                decision_at=original.decision_at,
                request_digest=original.request_digest,
            ).status
            == "matched"
        )
        return
    changed = _with_report(source, changed_report)
    result = evaluate_source_accounting(changed, check_deadline=_deadline)
    assert isinstance(result.result, AccountingRefusal)
    assert result.result.reason == "unsupported_diagnostic"


def test_selected_fact_ids_are_results_of_semantics_instead_of_selection_inputs(
    sources,
):
    source = sources["historical"]
    root = _root(source)
    ids = {
        node.get("id"): "renamed-source-fact-" + str(index)
        for index, node in enumerate(root.xpath('//*[local-name()="nonFraction"]'))
    }
    for node in root.xpath('//*[local-name()="nonFraction"]'):
        node.set("id", ids[node.get("id")])
    for relationship in root.xpath('//*[local-name()="relationship"]'):
        relationship.set(
            "fromRefs",
            " ".join(
                ids.get(identity, identity)
                for identity in relationship.get("fromRefs", "").split()
            ),
        )
    focus = source.witness.witness.actual_focus
    witness = source.witness.model_copy(
        update={
            "witness": source.witness.witness.model_copy(
                update={
                    "actual_focus": focus.model_copy(
                        update={"fact_id": ids[focus.fact_id]}
                    )
                }
            )
        }
    )
    tagged, zeros, link, tables, bridges = _read_disclosures(
        replace(source, witness=witness), etree.tostring(root), check_deadline=_deadline
    )
    assert len(tagged) == 16
    assert all(
        f.transcription.fact_id.startswith("renamed-source-fact-") for f in tagged
    )
    assert all(bridge.residual == 0 for bridge in bridges)
    assert link.focus_id == ids[focus.fact_id] and len(zeros) == 2 and len(tables) == 3


def test_original_amount_difference_fails_a_whole_bridge_even_with_matching_transcription(
    sources,
):
    source = sources["historical"]
    root = _root(source)
    investment = _table(root, "Derivatives, net (a)")
    total = _row(investment, "Total").xpath('.//*[local-name()="nonFraction"]')[2]
    assert _text(total) == "57,588"
    total.text = "57,580"
    report = source.evidence.outcome.claim.report
    candidate = next(
        f
        for f in report.facts
        if f.concept == "us-gaap:ShortTermInvestments" and f.value == "57588000000"
    )
    report = report.model_copy(
        update={
            "facts": (
                *report.facts,
                candidate.model_copy(update={"value": "57580000000"}),
            )
        }
    )
    changed = replace(
        source,
        evidence=source.evidence.model_copy(
            update={
                "outcome": source.evidence.outcome.model_copy(
                    update={
                        "claim": source.evidence.outcome.claim.model_copy(
                            update={"report": report}
                        )
                    }
                )
            }
        ),
    )
    with pytest.raises(_Refusal) as refusal:
        _read_disclosures(changed, etree.tostring(root), check_deadline=_deadline)
    assert refusal.value.reason == "reconciliation_mismatch"


def test_report_cardinality_bound_is_an_operational_error(sources):
    source = sources["historical"]
    report = source.evidence.outcome.claim.report
    changed = replace(
        source,
        evidence=source.evidence.model_copy(
            update={
                "outcome": source.evidence.outcome.model_copy(
                    update={
                        "claim": source.evidence.outcome.claim.model_copy(
                            update={
                                "report": report.model_copy(
                                    update={"facts": report.facts * 5}
                                )
                            }
                        )
                    }
                )
            }
        ),
    )
    with pytest.raises(SnapshotError) as failure:
        evaluate_source_accounting(changed, check_deadline=_deadline)
    assert failure.value.code == "FISCAL_ACCOUNTING_BUDGET_EXCEEDED"


@pytest.mark.parametrize(
    "mutation",
    ("duplicate_role", "missing_predicate", "missing_bridge", "crossed_scope"),
)
def test_supported_result_cannot_describe_incomplete_or_crossed_evidence(
    sources, mutation
):
    result = evaluate_source_accounting(sources["historical"], check_deadline=_deadline)
    payload = json.loads(encode_accounting_record(result, check_deadline=_deadline))
    if mutation == "duplicate_role":
        payload["result"]["tagged"][1] = payload["result"]["tagged"][0]
    elif mutation == "missing_predicate":
        payload["result"]["link"]["from_refs"].clear()
    elif mutation == "missing_bridge":
        payload["result"]["bridges"].pop()
    else:
        payload["inputs"]["scope_json_b64"] = base64.b64encode(
            canonical_bytes(sources["current"].scope)
        ).decode("ascii")
    with pytest.raises(ValidationError):
        TypeAdapter(AccountingReplayRecordV3).validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "change",
    (
        "nonzero",
        "blank",
        "missing",
        "second_amount",
        "moved",
        "tagged",
        "bad_currency",
        "closing_sign",
    ),
)
def test_note5_current_assets_requires_each_untagged_location_zero(sources, change):
    source = sources["historical"]
    root = _root(source)
    derivative = _table(root, "Reported as")
    row = _row(
        derivative,
        "Other long-term liabilities"
        if change == "blank"
        else "Other current liabilities",
    )
    cell = row[3]
    assert _text(cell) == "0" and not cell.xpath('.//*[local-name()="nonFraction"]')
    if change in {"nonzero", "blank", "second_amount"}:
        _rename(
            cell, "0", {"nonzero": "40", "blank": "", "second_amount": "0 40"}[change]
        )
    elif change == "missing":
        row.remove(cell)
    elif change == "moved":
        _rename(cell, "0", "")
        row[2].text = "0"
    elif change == "tagged":
        tag = copy.deepcopy(
            _row(derivative, "Cash collateral received").xpath(
                './/*[local-name()="nonFraction"]'
            )[0]
        )
        tag.set("id", "synthetic-zero")
        cell.clear()
        cell.append(tag)
    elif change == "bad_currency":
        row[2].text = "€"
    else:
        row[4].text = "-"
    with pytest.raises(_Refusal) as error:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert error.value.reason in {"missing_disclosure", "contradictory_disclosure"}


@pytest.mark.parametrize("text", [" + 10,000", " -", " +", " )", " €"])
def test_whole_balance_sheet_cell_has_one_visible_amount(sources, text):
    source = sources["historical"]
    root = _root(source)
    row = _row(_table(root, "Total assets"), "Short-term investments")
    (tag,) = row[3].xpath('.//*[local-name()="nonFraction"]')
    assert _text(tag) == "57,588"
    tag.tail = text
    with pytest.raises(_Refusal) as error:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert error.value.reason == "contradictory_disclosure"


@pytest.mark.parametrize("new_edge", [True, False])
def test_focus_rejects_a_second_linked_footnote(sources, new_edge):
    source = sources["historical"]
    root = _root(source)
    focus = _row(_table(root, "Derivatives, net (a)"), "Derivatives, net (a)")[
        25
    ].xpath('.//*[local-name()="nonFraction"]')[0]
    (edge,) = [
        n
        for n in root.xpath('//*[local-name()="relationship"]')
        if focus.get("id") in n.get("fromRefs", "").split()
    ]
    (original,) = root.xpath("//*[@id=$target]", target=edge.get("toRefs"))
    paragraph = original.getparent().getparent()
    other = copy.deepcopy(paragraph)
    (note,) = other.xpath('.//*[local-name()="footnote"]')
    note.clear()
    note.set("id", "additional-footnote")
    note.text = (
        "These short-term investments are excluded from the Note 5 reconciliation."
    )
    paragraph.addnext(other)
    if new_edge:
        second = copy.deepcopy(edge)
        second.set("fromRefs", focus.get("id"))
        second.set("toRefs", note.get("id"))
        edge.addnext(second)
    else:
        edge.set("toRefs", edge.get("toRefs") + " " + note.get("id"))
    with pytest.raises(_Refusal) as error:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert error.value.reason == "contradictory_disclosure"


@pytest.mark.parametrize(
    "change",
    [
        "repeated_bridge",
        "coefficient",
        "input",
        "output",
        "residual",
        "allowance",
        "swapped_roles",
        "semantic_fact_id",
        "review_value",
        "wrong_row",
        "swapped_cells",
        "swapped_contexts",
        "missing_plain_zero",
        "duplicate_plain_zero",
        "swapped_plain_cells",
        "plain_amount",
        "policy",
    ],
)
def test_supported_json_binds_all_facts_and_exact_bridges(sources, change):
    result = evaluate_source_accounting(sources["historical"], check_deadline=_deadline)
    payload = json.loads(encode_accounting_record(result, check_deadline=_deadline))
    bridges = payload["result"]["bridges"]
    facts = payload["result"]["tagged"]
    zeros = payload["result"]["plain_zeros"]
    if change == "repeated_bridge":
        bridges[:] = [bridges[0]] * 5
    elif change == "coefficient":
        bridges[3]["terms"][1]["coefficient"] = 1
    elif change == "input":
        bridges[1]["terms"][0]["fact_id"] = facts[0]["transcription"]["fact_id"]
    elif change == "output":
        bridges[1]["result_fact_id"] = facts[0]["transcription"]["fact_id"]
    elif change in ("residual", "allowance"):
        bridges[0]["residual" if change == "residual" else "precision_allowance"] = "1"
    elif change in (
        "swapped_roles",
        "semantic_fact_id",
        "swapped_cells",
        "swapped_contexts",
    ):
        field = {
            "swapped_roles": "role",
            "semantic_fact_id": "fact_id",
            "swapped_cells": "cell",
            "swapped_contexts": "context",
        }[change]
        if field == "fact_id":
            facts = [f["transcription"] for f in facts]
        facts[0][field], facts[1][field] = facts[1][field], facts[0][field]
    elif change == "review_value":
        facts[0]["transcription"]["value"] = "1000"
    elif change == "wrong_row":
        facts[0]["row_label"] = facts[1]["row_label"]
    elif change == "missing_plain_zero":
        zeros.pop()
    elif change == "duplicate_plain_zero":
        zeros[1] = zeros[0]
    elif change == "swapped_plain_cells":
        zeros[0]["cell"], zeros[1]["cell"] = zeros[1]["cell"], zeros[0]["cell"]
    elif change == "plain_amount":
        zeros[0]["cell"]["text"] = "40"
    else:
        payload["result"]["policy"]["definition_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        TypeAdapter(AccountingReplayRecordV3).validate_json(json.dumps(payload))


_ORIGINAL_ROLES = {
    "investment_debt": "F_55c0d452-6105-47b7-a546-cb06cc0fef9f",
    "investment_equity": "F_92609416-6cd6-47f2-b628-7cbff6846c24",
    "investment_cash": "F_64171302-7fe6-4afb-9bc7-168ca0507b97",
    "investment_derivative": "F_e576e4c8-d767-424a-9025-00f821500f56",
    "investment_total": "F_1f658e34-f0aa-460f-8e5c-762636fb9ec5",
    "balance_cash": "F_eadcd0b0-a481-4ada-9f13-5eb28fb4e067",
    "balance_investments": "F_1f063d5d-6fb8-4593-99e2-3f1b4fc3d47d",
    "balance_combined": "F_0519fc30-5e2e-4d82-b3d0-43994a5e9503",
    "derivative_gross": "F_35e8354d-c8ba-496f-a2d4-7d34d39da798",
    "derivative_offset": "F_273aa024-d4d9-45a3-a109-a651061732d8",
    "derivative_collateral": "F_4c095205-a9d8-422e-813a-61c2290727f7",
    "derivative_net": "F_1c18b1eb-74d4-4776-88c8-44aee1020327",
    "derivative_short_term": "F_5c9503f0-0e13-4eba-a4b9-e68c16567b4d",
    "derivative_current": "F_ba6612f6-1aa3-49c6-937f-1cdd6d5b3b9c",
    "derivative_noncurrent": "F_0ec14f68-b8f3-4d63-9ca2-b2e47ff22162",
    "derivative_location_total": "F_e1c73f1f-dad3-43f5-a71f-998dab9ea3cd",
}

_ORIGINAL_ENDPOINTS = (
    "F_f0d5f95f-c42d-491c-a292-98f823a5d252",
    "F_8898ec44-106c-46b1-85fc-327f33933e9b",
    "F_aa96b429-5c22-4685-be06-59b4816dbfdb",
    "F_e576e4c8-d767-424a-9025-00f821500f56",
    "F_962db4e9-3099-449b-8785-aebd14e0a400",
    "F_64cd6cbc-dbdf-4fe1-9515-6567502692c5",
    "F_5a7e325a-f8ae-4353-b966-b03b2a8179bc",
    "F_e938995b-d17f-484a-88f7-e93ebe0a95aa",
)


@pytest.fixture(scope="module")
def historical_wire(sources):
    return encode_accounting_record(
        evaluate_source_accounting(sources["historical"], check_deadline=_deadline),
        check_deadline=_deadline,
    )


@pytest.mark.parametrize(
    "case,scope_digest,old_scope",
    (
        (
            "historical",
            "68f368879d6519683cef7a4468115d8ca7b103ba23bf92bc6302b169e93f4cba",
            "bbf75747ea932170b4a5654fd6f68f2e9258695f19f29233db4766b98bb61edd",
        ),
        (
            "current",
            "fde62d67d3b0993fe1ab08e9fb1f6b8d4b9fe76dc3c7563b35f467c96ce7be11",
            "9535ce9796b051e7ad1b3687b2e91fda45e226e955633f75f50c9969ee2ad360",
        ),
    ),
)
def test_current_mapping_and_original_scope_keep_distinct_identities(
    sources, case, scope_digest, old_scope
):
    source = sources[case]
    assert source.scope.scope_digest == scope_digest
    path = (
        Path(os.environ["ISSUE495_RETAINED_EVIDENCE_ROOT"])
        / "source-accounting-policy-fixed"
        / f"{case}.policy-outcome.json"
    )
    original = FiscalSourceUseScopeV1.model_validate_json(
        json.dumps(json.loads(path.read_bytes())["scope"])
    )
    assert original.scope_digest == old_scope
    assert original.mapping_policy_digest != source.scope.mapping_policy_digest
    assert original.witness_ref == source.scope.witness_ref
    assert original.source_validation_ref == source.scope.source_validation_ref
    live = evaluate_source_accounting(
        replace(source, scope=original), check_deadline=_deadline
    )
    assert live.result.reason == "source_scope_mismatch"
    assert (
        read_accounting_record(
            encode_accounting_record(live, check_deadline=_deadline),
            check_deadline=_deadline,
        ).result
        == live.result
    )


@pytest.mark.parametrize(
    "change",
    (
        "absent_link",
        "contrary_text",
        "matched_no_witness",
        "comparative",
        "balanced_disagreement",
        "type_string",
        "type_bool",
        "missing_default",
        "same_shape",
        "table_census",
    ),
)
def test_normal_adapter_replays_business_claim_before_any_type_coercion(
    historical_wire, sources, change
):
    payload = json.loads(historical_wire)
    claim = payload["result"]
    by_role = {slot["role"]: slot for slot in claim["tagged"]}
    if change == "absent_link":
        claim["link"]["from_refs"] = []
    elif change == "contrary_text":
        claim["link"]["footnote"]["text"] = (
            "Excludes these short-term investments from Note 5."
        )
    elif change == "matched_no_witness":
        raw_scope = json.loads(base64.b64decode(payload["inputs"]["scope_json_b64"]))
        raw_scope.update(validation_kind="complete_matched", witness_ref=None)
        scope = FiscalSourceUseScopeV1.model_validate_json(json.dumps(raw_scope))
        live = evaluate_source_accounting(
            replace(sources["historical"], scope=scope), check_deadline=_deadline
        )
        assert live.result.reason == "source_scope_mismatch"
        payload["inputs"]["scope_json_b64"] = base64.b64encode(
            canonical_bytes(scope)
        ).decode()
    elif change == "comparative":
        by_role["derivative_offset"]["transcription"]["fact"]["instant"] = "2024-06-30"
    elif change == "balanced_disagreement":
        for role, amount, lexical in (
            ("derivative_short_term", "-2000000", "2"),
            ("derivative_current", "119000000", "119"),
        ):
            slot = by_role[role]
            fact = slot["transcription"]
            fact["value"] = fact["fact"]["value"] = amount
            fact["raw_lexical"] = lexical
            slot["cell"]["text"] = "( " + lexical if amount.startswith("-") else lexical
    elif change == "type_string":
        by_role["derivative_offset"]["transcription"]["fact"]["scale"] = "6"
    elif change == "type_bool":
        claim["bridges"][0]["terms"][0]["coefficient"] = True
    elif change == "missing_default":
        del by_role["investment_debt"]["transcription"]["fact"]["period_start"]
    elif change == "same_shape":
        claim["link"]["container"] = claim["link"]["footnote"]
    else:
        claim["tables"][0]["row_kinds"].pop()
    with pytest.raises(ValidationError, match="differs from complete original replay"):
        TypeAdapter(AccountingReplayRecordV3).validate_json(json.dumps(payload))


@pytest.mark.parametrize("name", tuple(_ORIGINAL_ROLES))
def test_each_original_role_is_selected_then_checks_its_reported_context(sources, name):
    source = sources["historical"]
    root = _root(source)
    (node,) = root.xpath("//*[@id=$identity]", identity=_ORIGINAL_ROLES[name])
    node.set("contextRef", "context-absent-from-original")
    with pytest.raises(_Refusal, match="context or unit") as refused:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert refused.value.reason == "fact_context_mismatch"


@pytest.mark.parametrize("endpoint", _ORIGINAL_ENDPOINTS)
def test_each_declared_footnote_endpoint_is_required(sources, endpoint):
    source = sources["historical"]
    root = _root(source)
    (edge,) = root.xpath(
        '//*[local-name()="relationship" and contains(@fromRefs,$id)]', id=endpoint
    )
    edge.set(
        "fromRefs",
        " ".join(item for item in edge.get("fromRefs").split() if item != endpoint),
    )
    with pytest.raises(_Refusal) as refused:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert refused.value.reason == "contradictory_disclosure"


@pytest.mark.parametrize(
    "change",
    (
        "duplicate",
        "dangling",
        "wrong_existing",
        "unknown_arcrole",
        "unknown_link_role",
        "additional_arcrole",
        "two_destinations",
        "note_continuation",
        "relocated_note",
    ),
)
def test_original_focus_accounts_for_all_applicable_edges(sources, change):
    source = sources["historical"]
    root = _root(source)
    (edge,) = root.xpath(
        '//*[local-name()="relationship" and contains(@fromRefs,$id)]',
        id=_ORIGINAL_ROLES["investment_derivative"],
    )
    (note,) = root.xpath("//*[@id=$id]", id=edge.get("toRefs"))
    if change in ("duplicate", "dangling", "wrong_existing"):
        refs = edge.get("fromRefs").split()
        refs[0] = {
            "duplicate": refs[-1],
            "dangling": "absent",
            "wrong_existing": _ORIGINAL_ROLES["investment_debt"],
        }[change]
        edge.set("fromRefs", " ".join(refs))
    elif change == "additional_arcrole":
        other = copy.deepcopy(edge)
        other.set("arcrole", "urn:other-disclosure")
        edge.addnext(other)
    elif change in ("unknown_arcrole", "unknown_link_role"):
        edge.set("arcrole" if change == "unknown_arcrole" else "linkRole", "urn:other")
    elif change == "two_destinations":
        edge.set("toRefs", edge.get("toRefs") + " unrelated-note")
    elif change == "note_continuation":
        note.set("continuedAt", "another-note")
    else:
        root.append(note.getparent().getparent())
    with pytest.raises(_Refusal) as refused:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert refused.value.reason == "contradictory_disclosure"


@pytest.mark.parametrize(
    "table_label,row_label,target",
    (
        ("Reported as", "Other current liabilities", "uncaptioned"),
        ("Total assets", "Short-term investments", "uncaptioned"),
        ("Derivatives, net (a)", "Cash", "uncaptioned"),
        ("Reported as", "Reported as", "amount"),
        ("Derivatives, net (a)", "September 30, 2024", "amount"),
        ("Reported as", "(In millions)", "currency"),
        ("Reported as", "Other current liabilities", "closing"),
        ("Derivatives, net (a)", "Derivatives, net (a)", "span"),
        ("Reported as", "Interest rate contracts", "new_caption"),
        ("Total assets", "Short-term investments", "extra_tag"),
        ("Reported as", "Gross amounts of derivatives", "blank_inline"),
    ),
)
def test_all_physical_rows_and_adornments_are_consumed(
    sources, table_label, row_label, target
):
    source = sources["historical"]
    root = _root(source)
    table = _table(root, table_label)
    row = _row(table, row_label)
    if target in ("uncaptioned", "blank_inline"):
        extra = etree.Element(row.tag)
        for i in range(9):
            cell = etree.SubElement(extra, row[0].tag)
            if i == 3:
                if target == "uncaptioned":
                    cell.text = "40"
                else:
                    etree.SubElement(
                        cell, "{http://www.xbrl.org/2013/inlineXBRL}footnote"
                    )
        row.addnext(extra)
    elif target == "new_caption":
        _rename(row[0], row_label, "Unidentified instrument")
    elif target == "span":
        row[24].set("colspan", "2")
    elif target == "extra_tag":
        tag = copy.deepcopy(row[3].xpath('.//*[local-name()="nonFraction"]')[0])
        tag.set("id", "distinct-additional-amount")
        row[3].append(tag)
    else:
        row[{"amount": 3, "currency": 1, "closing": 4}[target]].text = "40"
    with pytest.raises(_Refusal) as refused:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert refused.value.reason in {
        "incomplete_bridge",
        "ambiguous_disclosure",
        "contradictory_disclosure",
        "missing_disclosure",
    }


def _changed_amounts(source, changes):
    root = _root(source)
    report = source.evidence.outcome.claim.report
    facts = list(report.facts)
    for role, delta_millions in changes:
        (n,) = root.xpath("//*[@id=$id]", id=_ORIGINAL_ROLES[role])
        lexical = _text(n)
        signed = Decimal(lexical.replace(",", "")) * (-1 if n.get("sign") == "-" else 1)
        adjusted = signed + delta_millions
        assert signed.is_signed() == adjusted.is_signed()
        n.text = f"{abs(adjusted):,}"
        for fact in report.facts:
            if (
                fact.context_id == n.get("contextRef")
                and fact.concept == n.get("name")
                and fact.is_numeric
                and Decimal(fact.value) == signed * 1000000
            ):
                facts.append(fact.model_copy(update={"value": str(adjusted * 1000000)}))
    raw = report.model_copy(update={"facts": tuple(facts)})
    outcome = source.evidence.outcome
    evidence = source.evidence.model_copy(
        update={
            "outcome": outcome.model_copy(
                update={"claim": outcome.claim.model_copy(update={"report": raw})}
            )
        }
    )
    return replace(source, evidence=evidence), etree.tostring(root)


@pytest.mark.parametrize(
    "changes",
    (
        (("derivative_short_term", -1), ("derivative_current", 1)),
        (("derivative_gross", 1), ("derivative_net", 1)),
    ),
)
def test_exact_equalities_are_independent_of_all_five_tolerances(sources, changes):
    source, member = _changed_amounts(sources["historical"], changes)
    with pytest.raises(
        _Refusal, match="cross-note derivative amount or both Note 5 totals"
    ) as rejected:
        _read_disclosures(source, member, check_deadline=_deadline)
    assert rejected.value.reason == "contradictory_disclosure"


@pytest.mark.parametrize(
    "index,roles,last_inside",
    (
        (0, ("investment_debt",), 2),
        (1, ("balance_investments", "balance_combined"), 1),
        (2, ("balance_combined",), 1),
        (3, ("derivative_gross",), 2),
        (4, ("derivative_current",), 2),
    ),
)
def test_each_bridge_accepts_last_attainable_residual_and_refuses_next(
    sources, index, roles, last_inside
):
    for delta in (last_inside, last_inside + 1):
        source, member = _changed_amounts(
            sources["historical"], [(role, delta) for role in roles]
        )
        if delta == last_inside:
            *_, bridges = _read_disclosures(source, member, check_deadline=_deadline)
            assert abs(bridges[index].residual) == delta * 1000000
        else:
            with pytest.raises(_Refusal) as refused:
                _read_disclosures(source, member, check_deadline=_deadline)
            assert refused.value.reason == "reconciliation_mismatch"


@pytest.mark.parametrize(
    "change",
    (
        "duplicate_outer",
        "duplicate_inner",
        "noncanonical_base64",
        "noncanonical_json",
        "nonfinite",
        "outer_cap",
        "depth",
        "cancel",
        "deadline",
    ),
)
def test_offline_bytes_and_operational_boundaries(historical_wire, change):
    raw = historical_wire
    check = _deadline
    expected = ValueError
    if change == "duplicate_outer":
        raw = b'{"protocol":"discarded",' + raw[1:]
    elif change == "outer_cap":
        raw = b" " * (9 * 1024 * 1024 + 1)
        expected = SnapshotError
    elif change == "depth":
        raw = b"[" * 65 + b"0" + b"]" * 65
        expected = SnapshotError
    elif change == "cancel":

        def check():
            raise asyncio.CancelledError()

        expected = asyncio.CancelledError
    elif change == "deadline":
        stop = monotonic() + 0.001

        def check():
            left = stop - monotonic()
            if left <= 0:
                raise SnapshotError("DEADLINE_EXCEEDED", "absolute budget exhausted")
            return left

        expected = SnapshotError
    else:
        body = json.loads(raw)
        field = "scope_json_b64"
        inner = base64.b64decode(body["inputs"][field])
        if change == "duplicate_inner":
            inner = b'{"validation_kind":"complete_matched",' + inner[1:]
        elif change == "nonfinite":
            inner = b'{"value":NaN,' + inner[1:]
        elif change == "noncanonical_json":
            inner += b" "
        body["inputs"][field] = base64.b64encode(inner).decode()
        if change == "noncanonical_base64":
            body["inputs"][field] += " "
        raw = json.dumps(body).encode()
    with pytest.raises(expected):
        read_accounting_record(raw, check_deadline=check)


@pytest.mark.parametrize(
    "path,new_value",
    (
        (("source_validation_ref", "media_type"), "text/plain"),
        (("source_validation_ref", "role"), "different-filing"),
        (("request_digest",), "1" * 64),
        (("filing", "form"), "10-K"),
        (("cutoff",), "2024-11-03T00:00:00Z"),
        (("source_available_at",), "2024-11-03T00:00:00Z"),
        (("runtime", "validation_profile_digest"), "1" * 64),
        (("integrity", "arelle_version"), "2.47.5"),
        (("source_responses",), "empty"),
        (("raw_report_digest",), "1" * 64),
        (("raw_report_findings_digest",), "1" * 64),
        (("raw_report_fact_digest",), "1" * 64),
        (("actions", 0, "report_ref", "role"), "unrelated-report"),
        (("actions", 0, "request", "profile_digest"), "1" * 64),
        (("actions", 0, "representation"), "archive"),
        (("actions", 0, "delivery", "report_content_hash"), "1" * 64),
        (("applicability_policy_digest",), "1" * 64),
        (("filing_context", "filing_date"), "2024-11-01"),
        (("raw_finding", "message"), "Different recorded observation"),
    ),
)
def test_schema_valid_witness_still_requires_source_agreement(sources, path, new_value):
    source = sources["historical"]
    payload = json.loads(source.witness.model_dump_json())
    parent = payload["witness"]
    for field in path[:-1]:
        parent = parent[field]
    parent[path[-1]] = [] if new_value == "empty" else new_value
    witness = SignedFiscalDiagnosticFocusWitnessV1.model_validate_json(
        json.dumps(payload)
    )
    scope = source.scope.model_dump(mode="json")
    scope["witness_ref"] = _ref(
        witness.artifact_id, witness, "fiscal-diagnostic-focus-witness-v1"
    ).model_dump(mode="json")
    changed = replace(
        source,
        scope=FiscalSourceUseScopeV1.model_validate_json(json.dumps(scope)),
        witness=witness,
    )
    result = evaluate_source_accounting(changed, check_deadline=_deadline).result
    assert result.reason == (
        "unsupported_diagnostic"
        if path[0] in {"filing_context", "raw_finding"}
        else "source_scope_mismatch"
    )


@pytest.mark.parametrize(
    "side,path",
    (
        ("scope", ("permitted_inputs", 0, "quality")),
        ("source", ("request", "filing", "primary_document")),
        ("source", ("request", "filing", "form")),
        ("source", ("outcome", "integrity", "quality_decision")),
        ("source", ("outcome", "runtime", "validation_profile_digest")),
        ("source", ("outcome", "claim", "metadata_status")),
        ("source", ("outcome", "responses", 0, "content_hash")),
        ("source", ("outcome", "claim", "source", "available_at")),
    ),
)
def test_owner_rejects_internally_inconsistent_source_before_policy(
    sources, side, path
):
    source = sources["historical"]
    owner = source.scope if side == "scope" else source.evidence
    payload = owner.model_dump(mode="json")
    part = payload
    for step in path[:-1]:
        part = part[step]
    field = path[-1]
    part[field] = {
        "quality": "verified",
        "primary_document": "other.htm",
        "form": "10-K",
        "quality_decision": "allow",
        "validation_profile_digest": "1" * 64,
        "metadata_status": "refused",
        "content_hash": "1" * 64,
        "available_at": "2099-11-01T00:00:00Z",
    }[field]
    with pytest.raises(ValidationError):
        type(owner).model_validate_json(json.dumps(payload))


def test_missing_diagnostic_with_another_active_blocker_has_no_opinion(sources):
    source = sources["historical"]
    original = source.evidence.outcome.claim.report
    remainder = tuple(
        finding for finding in original.findings if finding.code != "DQC.US.0015.5970"
    )
    alternate = ArelleFindingV1(
        code="other-active", severity="error", message="Different blocking diagnostic"
    )
    modified = _with_report(
        source, original.model_copy(update={"findings": (*remainder, alternate)})
    )
    result = evaluate_source_accounting(modified, check_deadline=_deadline).result
    assert result.reason == "unsupported_diagnostic"


@pytest.mark.parametrize(
    "nonnumeric",
    (
        "transform",
        "transform_namespace",
        "divide",
        "entity_scheme",
        "axis_namespace",
        "member_namespace",
        "duration",
        "extra_period",
        "unsigned_offset",
        "ambiguous_missing_instant",
    ),
)
def test_reported_fact_requires_complete_original_context_and_transform(
    sources, nonnumeric
):
    source = sources["historical"]
    root = _root(source)
    (fact,) = root.xpath(
        "//*[@id=$id]",
        id=_ORIGINAL_ROLES[
            "derivative_short_term"
            if nonnumeric != "unsigned_offset"
            else "derivative_offset"
        ],
    )
    (ctx,) = root.xpath("//*[@id=$id]", id=fact.get("contextRef"))
    (unit,) = root.xpath("//*[@id=$id]", id=fact.get("unitRef"))
    if nonnumeric == "transform":
        fact.set("format", "ixt:num-comma-decimal")
    elif nonnumeric == "transform_namespace":
        fact.set("format", "us-gaap:num-dot-decimal")
    elif nonnumeric == "divide":
        etree.SubElement(unit, unit.tag.replace("unit", "divide"))
    elif nonnumeric == "entity_scheme":
        ctx.xpath('.//*[local-name()="identifier"]')[0].set("scheme", "other")
    elif nonnumeric in {"axis_namespace", "member_namespace"}:
        element = ctx.xpath('.//*[local-name()="explicitMember"]')[0]
        if nonnumeric == "axis_namespace":
            element.set("dimension", "iso4217:BalanceSheetLocationAxis")
        else:
            element.text = "iso4217:ShortTermInvestmentsMember"
    elif nonnumeric in {"duration", "extra_period"}:
        period = ctx.xpath('.//*[local-name()="period"]')[0]
        etree.SubElement(
            period,
            period.tag.replace("period", "endDate")
            if nonnumeric == "duration"
            else period.tag.replace("period", "forever"),
        )
    elif nonnumeric == "unsigned_offset":
        fact.set("sign", "-")
    else:
        inst = ctx.xpath('.//*[local-name()="instant"]')[0]
        inst.getparent().remove(inst)
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason in {
        "unsupported_numeric",
        "fact_context_mismatch",
        "contradictory_disclosure",
    }


@pytest.mark.parametrize(
    "variant", ("unknown", "rule_warning", "message_error", "reversed_severities")
)
def test_target_diagnostic_needs_original_active_error_rule_and_warning_message(
    sources, variant
):
    source = sources["historical"]
    report = source.evidence.outcome.claim.report
    target = source.witness.witness.raw_finding
    edits = {
        "unknown": {"rule_effective_date": None},
        "rule_warning": {"rule_severity": "warning"},
        "message_error": {"severity": "error"},
        "reversed_severities": {"rule_severity": "warning", "severity": "error"},
    }[variant]
    changed = target.model_copy(update=edits)
    report = report.model_copy(
        update={
            "findings": tuple(changed if f == target else f for f in report.findings)
        }
    )
    original = source.evidence.outcome.claim
    claim = evaluate_fiscal_issuer(
        report,
        filing=original.filing,
        source=original.source,
        decision_at=original.decision_at,
        request_digest=original.request_digest,
    )
    if variant == "rule_warning":
        assert claim.status == "matched"
        return
    assert claim.status == "refused"
    result = evaluate_source_accounting(
        _with_report(source, report), check_deadline=_deadline
    ).result
    assert result.reason == "unsupported_diagnostic"


@pytest.mark.parametrize(
    "field,limit",
    (
        ("findings", 256),
        ("facts", 5000),
        ("action_refs", 32),
        ("responses", 64),
        ("permitted_inputs", 128),
    ),
)
def test_capsule_preflights_owner_cardinality_before_large_model(
    historical_wire, field, limit
):
    payload = json.loads(historical_wire)
    media = "scope_json_b64" if field == "permitted_inputs" else "validation_json_b64"
    raw = json.loads(base64.b64decode(payload["inputs"][media]))
    container = raw if field == "permitted_inputs" else raw["outcome"]
    if field in ("facts", "findings"):
        container = container["claim"]["report"]
    container[field] = [None] * (limit + 1)
    payload["inputs"][media] = base64.b64encode(canonical_bytes(raw)).decode()
    with pytest.raises(SnapshotError) as rejected:
        TypeAdapter(AccountingReplayRecordV3).validate_json(json.dumps(payload))
    assert rejected.value.code == "FISCAL_ACCOUNTING_BUDGET_EXCEEDED"


def test_live_archive_and_capsule_agree_on_changed_primary_archive(sources):
    source = sources["historical"]
    live = evaluate_source_accounting(
        replace(source, archive=source.archive + b" "), check_deadline=_deadline
    )
    assert live.result.reason == "source_hash_mismatch"
    record = read_accounting_record(
        encode_accounting_record(live, check_deadline=_deadline),
        check_deadline=_deadline,
    )
    assert record.result == live.result
    assert record.review() is None


def test_duplicate_outer_keys_are_only_observable_at_the_byte_entrypoint(
    historical_wire,
):
    raw = b'{"protocol":"discarded",' + historical_wire[1:]
    with pytest.raises(ValueError, match="Duplicate JSON property"):
        read_accounting_record(raw, check_deadline=_deadline)
    assert (
        TypeAdapter(AccountingReplayRecordV3)
        .validate_json(raw, strict=True)
        .result.kind
        == "supported"
    )


def test_contrary_marked_note_in_investments_requires_an_unambiguous_destination(
    sources,
):
    source = sources["historical"]
    root = _root(source)
    (edge,) = root.xpath(
        '//*[local-name()="relationship" and contains(@fromRefs,$id)]',
        id=_ORIGINAL_ROLES["investment_derivative"],
    )
    (note,) = root.xpath("//*[@id=$id]", id=edge.get("toRefs"))
    container = note.getparent().getparent()
    other = copy.deepcopy(container)
    (new_note,) = other.xpath('.//*[local-name()="footnote"]')
    for child in tuple(new_note):
        new_note.remove(child)
    new_note.set("id", "unlinked-contrary-note")
    new_note.text = "This class is excluded."
    container.addnext(other)
    with pytest.raises(_Refusal, match="single marked") as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason == "contradictory_disclosure"


def test_local_dependency_failure_and_resolver_cancellation_propagate(
    sources, historical_wire, monkeypatch
):
    from fundamental_service import fiscal_source_accounting_policy as policy

    def resource_error():
        raise ValueError("Pinned DQC catalog identity differs")

    monkeypatch.setattr(policy, "_document_dates", resource_error)
    for operation in (
        lambda: evaluate_source_accounting(
            sources["historical"], check_deadline=_deadline
        ),
        lambda: TypeAdapter(AccountingReplayRecordV3).validate_json(historical_wire),
    ):
        with pytest.raises(SnapshotError) as error:
            operation()
        assert error.value.code == "FISCAL_ACCOUNTING_RESOURCE_UNAVAILABLE"


@pytest.mark.parametrize("field", ("source_validation_ref", "witness_ref"))
@pytest.mark.parametrize("attribute", ("role", "media_type", "content_hash"))
def test_exact_reference_fields_are_bound_to_their_originals(sources, field, attribute):
    source = sources["historical"]
    payload = source.scope.model_dump(mode="json")
    payload[field][attribute] = {
        "role": "other-document",
        "media_type": "text/plain",
        "content_hash": "8" * 64,
    }[attribute]
    scope = FiscalSourceUseScopeV1.model_validate_json(json.dumps(payload))
    result = evaluate_source_accounting(
        replace(source, scope=scope), check_deadline=_deadline
    ).result
    assert result.reason == "source_scope_mismatch"


def test_complete_matched_validation_is_outside_this_source_opinion(sources):
    source = sources["historical"]
    previous = source.evidence.outcome.claim
    report = previous.report.model_copy(
        update={
            "findings": tuple(
                f for f in previous.report.findings if f.code != "DQC.US.0015.5970"
            )
        }
    )
    claim = evaluate_fiscal_issuer(
        report,
        filing=previous.filing,
        source=previous.source,
        decision_at=previous.decision_at,
        request_digest=previous.request_digest,
    )
    assert claim.status == "matched"
    raw = source.evidence.model_dump(mode="json")
    outcome = raw["outcome"]
    outcome.pop("issue_codes")
    outcome.pop("rejection_ref", None)
    outcome.update(kind="complete_matched", claim=claim.model_dump(mode="json"))
    outcome["integrity"]["quality_decision"] = "pass"
    outcome["integrity"]["findings"] = [
        f for f in outcome["integrity"]["findings"] if f["code"] != "DQC.US.0015.5970"
    ]
    evidence = FiscalOriginalValidationEvidenceV1.model_validate_json(json.dumps(raw))
    resolved = replace(source, evidence=evidence)
    assert (
        evaluate_source_accounting(resolved, check_deadline=_deadline).result.reason
        == "unsupported_source"
    )


@pytest.mark.parametrize("bridge", range(5))
@pytest.mark.parametrize(
    "alter", ("coefficient", "input", "output", "residual", "allowance")
)
def test_each_serialized_bridge_is_an_exact_source_projection(
    historical_wire, bridge, alter
):
    payload = json.loads(historical_wire)
    row = payload["result"]["bridges"][bridge]
    if alter == "coefficient":
        row["terms"][0]["coefficient"] *= -1
    elif alter == "input":
        row["terms"][0]["fact_id"] = _ORIGINAL_ROLES["derivative_offset"]
    elif alter == "output":
        row["result_fact_id"] = _ORIGINAL_ROLES["derivative_offset"]
    else:
        row["residual" if alter == "residual" else "precision_allowance"] = "1"
    with pytest.raises(ValidationError, match="differs from complete original replay"):
        TypeAdapter(AccountingReplayRecordV3).validate_json(
            json.dumps(payload), strict=True
        )


@pytest.mark.parametrize(
    "mutation", ("split_in_section", "above_header", "past_last_row", "orphan_cell")
)
def test_census_rejects_unclassified_tables_and_cells_inside_original_section(
    sources, mutation
):
    source = sources["historical"]
    root = _root(source)
    table = _table(root, "Reported as")
    if mutation == "orphan_cell":
        etree.SubElement(table, table[0][0].tag).text = "40"
    elif mutation == "split_in_section":
        extra = etree.Element(table.tag)
        extra.append(copy.deepcopy(_row(table, "Reported as")))
        table.addnext(extra)
    else:
        row = etree.Element(table[0].tag)
        etree.SubElement(row, table[0][0].tag).text = "Unidentified disclosure"
        if mutation == "above_header":
            table.insert(0, row)
        else:
            table.append(row)
    with pytest.raises(_Refusal) as refused:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert refused.value.reason in {
        "incomplete_bridge",
        "contradictory_disclosure",
        "missing_disclosure",
    }


@pytest.mark.parametrize(
    "kind", ("literal", "digest", "base64_pad_bits", "media_budget")
)
def test_canonical_owner_media_must_survive_round_trip(historical_wire, kind):
    payload = json.loads(historical_wire)
    values = payload["inputs"]
    if kind == "base64_pad_bits":
        original = values["validation_json_b64"]
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        assert original.endswith("==")
        index = alphabet.index(original[-3])
        values["validation_json_b64"] = original[:-3] + alphabet[index + 1] + "=="
        assert base64.b64decode(values["validation_json_b64"]) == base64.b64decode(
            original
        )
    elif kind == "media_budget":
        values["witness_json_b64"] = "A" * (4 * ((32 * 1024 + 2) // 3) + 1)
    elif kind == "literal":
        values["archive_zip_b64"] = "application/zip"
    else:
        raw = json.loads(base64.b64decode(values["scope_json_b64"]))
        raw["mapping_policy_digest"] = "1" * 64
        values["scope_json_b64"] = base64.b64encode(
            canonical_bytes(FiscalSourceUseScopeV1.model_validate_json(json.dumps(raw)))
        ).decode()
    if kind == "media_budget":
        with pytest.raises(SnapshotError) as error:
            TypeAdapter(AccountingReplayRecordV3).validate_json(json.dumps(payload))
        assert error.value.code == "FISCAL_ACCOUNTING_BUDGET_EXCEEDED"
    else:
        with pytest.raises(ValidationError):
            TypeAdapter(AccountingReplayRecordV3).validate_json(json.dumps(payload))


@pytest.mark.parametrize("endpoint", _ORIGINAL_ENDPOINTS)
@pytest.mark.parametrize("change", ("concept", "date", "dimensions", "unit", "value"))
def test_every_linked_amount_matches_the_disclosed_column_date_dimension_currency_and_report(
    sources, endpoint, change
):
    source = sources["historical"]
    root = _root(source)
    (node,) = root.xpath("//*[@id=$id]", id=endpoint)
    original = node.get("contextRef")
    (context,) = root.xpath("//*[@id=$id]", id=original)
    (unit,) = root.xpath("//*[@id=$id]", id=node.get("unitRef"))
    if change == "concept":
        node.set(
            "name",
            "us-gaap:CashAndCashEquivalentsAtCarryingValue"
            if node.get("name") != "us-gaap:CashAndCashEquivalentsAtCarryingValue"
            else "us-gaap:DerivativeAssets",
        )
    elif change in ("date", "dimensions"):
        copy_context = copy.deepcopy(context)
        copy_context.set("id", "distinct-changed-context")
        if change == "date":
            (instant,) = copy_context.xpath('.//*[local-name()="instant"]')
            instant.text = (
                "2024-09-30" if instant.text == "2024-06-30" else "2024-06-30"
            )
        else:
            (member,) = copy_context.xpath('.//*[local-name()="explicitMember"]')
            member.text = "us-gaap:DebtSecuritiesMember"
        context.addnext(copy_context)
        node.set("contextRef", copy_context.get("id"))
    elif change == "unit":
        copy_unit = copy.deepcopy(unit)
        copy_unit.set("id", "distinct-foreign-unit")
        copy_unit[0].text = "iso4217:EUR"
        unit.addnext(copy_unit)
        node.set("unitRef", copy_unit.get("id"))
    else:
        node.text = "43"
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason in {
        "contradictory_disclosure",
        "fact_context_mismatch",
    }


_DISCLOSED_NUMERIC_IDS = tuple(
    dict.fromkeys((*_ORIGINAL_ROLES.values(), *_ORIGINAL_ENDPOINTS))
)
_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
_HTML = "http://www.w3.org/1999/xhtml"


@pytest.mark.parametrize("identity", _DISCLOSED_NUMERIC_IDS)
@pytest.mark.parametrize("nil", ("true", "1", "false", "0"))
def test_original_numeric_presence_is_required_for_every_role_and_link_endpoint(
    sources, identity, nil
):
    source = sources["historical"]
    root = _root(source)
    (node,) = root.xpath("//*[@id=$id]", id=identity)
    node.set(_XSI_NIL, nil)
    if nil in ("true", "1"):
        with pytest.raises(_Refusal) as rejected:
            _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
        assert rejected.value.reason == "unsupported_numeric"
    else:
        tagged, zeros, link, _, bridges = _read_disclosures(
            source, etree.tostring(root), check_deadline=_deadline
        )
        assert len(tagged) == 16 and len(zeros) == 2
        assert link.from_refs == _ORIGINAL_ENDPOINTS
        assert all(bridge.residual == 0 for bridge in bridges)


@pytest.mark.parametrize(
    "role", ("investment_debt", "investment_equity", "derivative_short_term")
)
@pytest.mark.parametrize("nil", ("garbage", "TRUE", "", "2"))
def test_unrecognized_original_nil_lexical_form_cannot_supply_a_value(
    sources, role, nil
):
    source = sources["historical"]
    root = _root(source)
    (node,) = root.xpath("//*[@id=$id]", id=_ORIGINAL_ROLES[role])
    node.set(_XSI_NIL, nil)
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason == "unsupported_numeric"


@pytest.mark.parametrize("nil", ("true", "1", "false", "0"))
def test_same_local_name_in_another_namespace_does_not_mean_xsi_nil(sources, nil):
    source = sources["historical"]
    root = _root(source)
    (node,) = root.xpath("//*[@id=$id]", id=_ORIGINAL_ROLES["investment_debt"])
    node.set("{urn:unrelated}nil", nil)
    tagged, _, _, _, _ = _read_disclosures(
        source, etree.tostring(root), check_deadline=_deadline
    )
    assert next(
        item for item in tagged if item.role == "investment_debt"
    ).transcription.value == Decimal("57589000000")


@pytest.mark.parametrize(
    "nil,present",
    ((" false ", True), ("\t0\n", True), (" true ", False), (" 1 ", False)),
)
def test_xsi_boolean_whitespace_retains_numeric_presence_semantics(
    sources, nil, present
):
    source = sources["historical"]
    root = _root(source)
    (node,) = root.xpath("//*[@id=$id]", id=_ORIGINAL_ROLES["investment_debt"])
    node.set(_XSI_NIL, nil)
    if present:
        tagged, _, _, _, _ = _read_disclosures(
            source, etree.tostring(root), check_deadline=_deadline
        )
        assert len(tagged) == 16
    else:
        with pytest.raises(_Refusal) as rejected:
            _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
        assert rejected.value.reason == "unsupported_numeric"


@pytest.mark.parametrize("identity", _DISCLOSED_NUMERIC_IDS)
def test_every_numeric_role_and_endpoint_must_be_visibly_disclosed(sources, identity):
    source = sources["historical"]
    root = _root(source)
    (node,) = root.xpath("//*[@id=$id]", id=identity)
    node.set("style", "display:none")
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason == "unsupported_presentation"


def _presentation_node(root, place):
    (fact,) = root.xpath("//*[@id=$id]", id=_ORIGINAL_ROLES["investment_debt"])
    if place == "fact":
        return fact
    if place == "wrapper":
        parent = fact.getparent()
        wrapper = etree.Element("{" + _HTML + "}span")
        parent.replace(fact, wrapper)
        wrapper.append(fact)
        return wrapper
    if place in ("td", "tr", "table"):
        return next(
            n for n in fact.iterancestors() if n.tag == "{" + _HTML + "}" + place
        )
    if place == "ancestor":
        return next(n for n in fact.iterancestors() if n.tag == "{" + _HTML + "}body")
    table = _table(root, "Derivatives, net (a)")
    if place == "date":
        return _row(table, "September 30, 2024")[0]
    if place == "column":
        return next(
            n
            for n in table.iter("{" + _HTML + "}td")
            if _text(n) == "Short-term Investments"
        )
    if place == "heading":
        return next(
            n
            for n in root.iter("{" + _HTML + "}p")
            if _text(n) == "NOTE 4 — INVESTMENTS"
        )
    note = root.xpath('//*[local-name()="footnote"]')[0]
    if place == "footnote":
        return note
    container = note.getparent().getparent()
    if place == "footnote_container":
        return container
    return next(n for n in container.iter("{" + _HTML + "}span") if _text(n) == "(a)")


@pytest.mark.parametrize(
    "place",
    (
        "fact",
        "wrapper",
        "td",
        "tr",
        "table",
        "ancestor",
        "date",
        "column",
        "heading",
        "footnote",
        "footnote_container",
        "marker",
    ),
)
@pytest.mark.parametrize(
    "attribute,value",
    (
        ("style", " DiSpLaY : NoNe ! IMPORTANT "),
        ("style", "visibility: HIDDEN"),
        ("style", "visibility:collapse!important"),
        ("hidden", ""),
    ),
)
def test_required_disclosure_text_and_all_presentation_ancestors_must_be_visible(
    sources, place, attribute, value
):
    source = sources["historical"]
    root = _root(source)
    _presentation_node(root, place).set(attribute, value)
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason == "unsupported_presentation"


@pytest.mark.parametrize(
    "caption", ("Other current liabilities", "Other long-term liabilities")
)
@pytest.mark.parametrize("place", ("cell", "wrapper", "row"))
def test_plain_zero_is_visible_in_its_original_cell_and_wrappers(
    sources, caption, place
):
    source = sources["historical"]
    root = _root(source)
    row = _row(_table(root, "Reported as"), caption)
    node = row[3] if place == "cell" else row if place == "row" else row[3][0]
    node.set("style", "display:none")
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason == "unsupported_presentation"


@pytest.mark.parametrize(
    "style",
    (
        "display:inline",
        "visibility:visible",
        " DISPLAY : INLINE !important ; VISIBILITY : VISIBLE ",
        "",
    ),
)
def test_explicit_visible_numeric_wrappers_preserve_the_disclosed_amount(
    sources, style
):
    source = sources["historical"]
    root = _root(source)
    _presentation_node(root, "wrapper").set("style", style)
    tagged, _, _, _, bridges = _read_disclosures(
        source, etree.tostring(root), check_deadline=_deadline
    )
    assert len(tagged) == 16 and all(item.residual == 0 for item in bridges)


@pytest.mark.parametrize(
    "style",
    (
        "opacity:0",
        "font-size:0",
        "width:0",
        "overflow:hidden",
        "color:transparent",
        "clip:rect(0,0,0,0)",
        "position:absolute;left:-10000px",
        "position:relative;top:-10000pt",
        "display:n\\6f ne",
        "display:/**/none",
        "display:var(--mode)",
        "unknown-property:value",
        "display:inline;display:none",
        "display:none;display:inline",
        "filter:opacity(0)",
    ),
)
def test_unprovable_presentation_is_refused_instead_of_treated_as_blank(sources, style):
    source = sources["historical"]
    root = _root(source)
    _presentation_node(root, "wrapper").set("style", style)
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason == "unsupported_presentation"


@pytest.mark.parametrize("payload", ("40", "0", "inline", "tail"))
def test_collapsed_geometry_cannot_hide_extra_money_inline_evidence_or_tail(
    sources, payload
):
    source = sources["historical"]
    root = _root(source)
    table = _table(root, "Reported as")
    row = next(n for n in table if "visibility:collapse" in n.get("style", ""))
    if payload == "inline":
        etree.SubElement(row[0], "{http://www.xbrl.org/2013/inlineXBRL}nonFraction")
    elif payload == "tail":
        row.tail = "40"
    else:
        row[0].text = payload
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason == "unsupported_presentation"


@pytest.mark.parametrize(
    "kind",
    (
        "style",
        "link",
        "script",
        "processing_instruction",
        "class",
        "template",
        "foreign_namespace",
        "ix_hidden",
    ),
)
def test_external_or_unknown_presentation_mechanisms_are_unsupported(sources, kind):
    source = sources["historical"]
    root = _root(source)
    if kind == "processing_instruction":
        root.addprevious(
            etree.ProcessingInstruction(
                "xml-stylesheet", 'href="other.css" type="text/css"'
            )
        )
        raw = etree.tostring(root.getroottree())
    else:
        if kind == "class":
            _presentation_node(root, "wrapper").set("class", "hidden-disclosure")
        elif kind in ("template", "foreign_namespace", "ix_hidden"):
            _presentation_node(root, "wrapper").tag = {
                "template": "{" + _HTML + "}template",
                "foreign_namespace": "{urn:other}span",
                "ix_hidden": "{http://www.xbrl.org/2013/inlineXBRL}hidden",
            }[kind]
        else:
            node = etree.SubElement(root, "{" + _HTML + "}" + kind)
            node.text = ".hidden-disclosure { display:none }"
        raw = etree.tostring(root)
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, raw, check_deadline=_deadline)
    assert rejected.value.reason == "unsupported_presentation"


@pytest.mark.parametrize(
    "attribute,lexical,accepted",
    (
        (_XSI_NIL, "\u00a0false", False),
        (_XSI_NIL, "0\u0085", False),
        (_XSI_NIL, "\u20030", False),
        ("scale", "６", False),
        ("scale", "٦", False),
        ("scale", "0_6", False),
        ("scale", "6\u00a0", False),
        ("scale", "\r\n+006\t", True),
        ("colspan", "２", False),
        ("colspan", "٢", False),
        ("colspan", "0_2", False),
        ("colspan", "\u00a02", False),
        ("colspan", " +002\t", True),
    ),
)
def test_synthetic_numeric_and_column_attributes_use_their_source_lexicals(
    sources, attribute, lexical, accepted
):
    source = sources["historical"]
    root = _root(source)
    target = _presentation_node(root, "column" if attribute == "colspan" else "fact")
    target.set(attribute, lexical)
    if accepted:
        tagged, _, _, _, _ = _read_disclosures(
            source, etree.tostring(root), check_deadline=_deadline
        )
        assert tagged[0].transcription.value == Decimal("57589000000")
    else:
        with pytest.raises(_Refusal) as refused:
            _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
        assert refused.value.reason == (
            "contradictory_disclosure"
            if attribute == "colspan"
            else "unsupported_numeric"
        )


@pytest.mark.parametrize("attribute", ("fromRefs", "toRefs"))
@pytest.mark.parametrize("separator", ("\t", "\r\n", "\u00a0", "\u2003"))
def test_synthetic_footnote_id_lists_keep_xml_whitespace_and_order(
    sources, attribute, separator
):
    source = sources["historical"]
    root = _root(source)
    (edge,) = root.xpath(
        '//*[local-name()="relationship" and contains(@fromRefs,$id)]',
        id=_ORIGINAL_ROLES["investment_derivative"],
    )
    edge.set(
        attribute, separator + separator.join(edge.get(attribute).split()) + separator
    )
    if separator in ("\t", "\r\n"):
        _, _, link, _, _ = _read_disclosures(
            source, etree.tostring(root), check_deadline=_deadline
        )
        assert link.from_refs == _ORIGINAL_ENDPOINTS
        assert link.to_ref == edge.get("toRefs").strip(" \t\r\n")
    else:
        with pytest.raises(_Refusal) as refused:
            _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
        assert refused.value.reason == "contradictory_disclosure"


@pytest.mark.parametrize(
    "place,style",
    (
        ("table", "display:flex"),
        ("tr", "display:flex"),
        ("tr", "display:inline"),
        ("tr", "display:inline-flex"),
        ("tr", "display:flex;width:70%;font-size:2pt"),
        ("td", "text-indent:60.5pt;vertical-align:top"),
        ("column", "display:flex"),
        ("column", "display:inline"),
        ("column", "width:1%;box-sizing:content-box"),
        ("ancestor", "width:1%"),
        ("heading", "display:inline-flex"),
        ("footnote", "display:flex"),
        ("fact", "font-size:2pt"),
        ("wrapper", "display\u00a0:inline"),
        ("wrapper", "display:inline!\u2003important"),
        ("wrapper", "display:inlİne"),
    ),
)
def test_synthetic_styles_must_match_a_disclosure_use(sources, place, style):
    source = sources["historical"]
    root = _root(source)
    _presentation_node(root, place).set("style", style)
    with pytest.raises(_Refusal) as refused:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert refused.value.reason == "unsupported_presentation"


@pytest.mark.parametrize("content", ("amount", "text", "tail"))
def test_synthetic_xhtml_line_break_has_only_a_visible_tail(sources, content):
    source = sources["historical"]
    root = _root(source)
    fact = _presentation_node(root, "fact")
    br = etree.Element("{" + _HTML + "}br")
    if content == "amount":
        fact.getparent().replace(fact, br)
        br.append(fact)
    else:
        lexical = fact.text
        fact.text = None
        fact.append(br)
        if content == "tail":
            br.tail = lexical
        else:
            br.text = lexical
    if content == "tail":
        tagged, _, _, _, _ = _read_disclosures(
            source, etree.tostring(root), check_deadline=_deadline
        )
        assert tagged[0].transcription.raw_lexical == "57,589"
    else:
        with pytest.raises(_Refusal) as rejected:
            _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
        assert rejected.value.reason == "unsupported_presentation"


@pytest.mark.parametrize(
    "change",
    ("width_swap", "narrow_container", "footnote_container", "normalized_original"),
)
def test_synthetic_table_geometry_depends_on_structure_and_order(sources, change):
    source = sources["historical"]
    root = _root(source)
    table = _presentation_node(root, "table")
    if change == "width_swap":
        first, second = table[0][:2]
        a, b = first.get("style"), second.get("style")
        first.set("style", b)
        second.set("style", a)
    elif change == "normalized_original":
        for node in (table, table[0][0], _presentation_node(root, "tr")):
            styles = [
                part.strip().upper() + " ! IMPORTANT"
                for part in node.get("style").split(";")
                if part.strip()
            ]
            node.set("style", "\t;\n".join(reversed(styles)))
        tagged, _, _, _, bridges = _read_disclosures(
            source, etree.tostring(root), check_deadline=_deadline
        )
        assert len(tagged) == 16 and all(b.residual == 0 for b in bridges)
        return
    else:
        container = etree.Element("{" + _HTML + "}div")
        if change == "narrow_container":
            container.set("style", "width:1%")
        else:
            note = _presentation_node(root, "footnote_container")
            container.attrib.update(note.attrib)
        table.getparent().replace(table, container)
        container.append(table)
    with pytest.raises(_Refusal) as refused:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert refused.value.reason == "unsupported_presentation"


@pytest.mark.parametrize(
    "identity",
    (
        _ORIGINAL_ROLES["investment_debt"],
        _ORIGINAL_ROLES["investment_equity"],
        _ORIGINAL_ENDPOINTS[-1],
    ),
)
def test_synthetic_explicit_inline_numeric_occurrence_retains_its_disclosed_column(
    sources, identity
):
    source = sources["historical"]
    root = _root(source)
    (occurrence,) = root.xpath("//*[@id=$id]", id=identity)
    occurrence.set("style", " VISIBILITY : visible ; DISPLAY: INLINE !Important ")
    facts, _, link, _, bridges = _read_disclosures(
        source, etree.tostring(root), check_deadline=_deadline
    )
    assert len(facts) == 16 and link.from_refs == _ORIGINAL_ENDPOINTS
    assert all(bridge.residual == 0 for bridge in bridges)


@pytest.mark.parametrize(
    "namespace,element",
    (
        (_HTML, "style"),
        (_HTML, "link"),
        (_HTML, "script"),
        ("http://www.w3.org/2000/svg", "style"),
        ("http://www.w3.org/2000/svg", "script"),
    ),
)
def test_document_wide_presentation_sources_refuse_all_supported_namespaces(
    sources, namespace, element
):
    source = sources["historical"]
    root = _root(source)
    svg = etree.SubElement(root, "{http://www.w3.org/2000/svg}svg")
    host = svg if namespace == "http://www.w3.org/2000/svg" else root
    etree.SubElement(host, "{" + namespace + "}" + element)
    with pytest.raises(_Refusal) as rejected:
        _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
    assert rejected.value.reason == "unsupported_presentation"


def test_benign_sibling_svg_graphic_keeps_local_shape_and_title(sources):
    source = sources["historical"]
    root = _root(source)
    svg = etree.SubElement(root, "{http://www.w3.org/2000/svg}svg")
    rectangle = etree.SubElement(
        svg,
        "{http://www.w3.org/2000/svg}rect",
        x="1",
        y="2",
        width="3",
        height="4",
        fill="blue",
    )
    etree.SubElement(
        rectangle, "{http://www.w3.org/2000/svg}title"
    ).text = "Local chart label"
    tagged, _, _, _, bridges = _read_disclosures(
        source, etree.tostring(root), check_deadline=_deadline
    )
    assert len(tagged) == 16
    assert all(bridge.residual == 0 for bridge in bridges)


@pytest.mark.parametrize(
    "suffix",
    (
        "",
        " !important",
        " ! IMPORTANT",
        " !\tIMPORTANT",
        " ! important",
        " ! ImPoRtAnT ",
    ),
)
def test_sec_caption_priority_preserves_case_sensitive_annotation_identity(
    sources, suffix
):
    source = sources["historical"]
    root = _root(source)
    (annotation,) = root.xpath(
        '//*[local-name()="span" and contains(@style,"F_488c65b3-e97c-456a-a919-0b3d8183dd75")]'
    )
    original = next(
        declaration.strip()
        for declaration in annotation.get("style").split(";")
        if declaration.strip().startswith("-sec-ix-hidden:")
    )
    annotation.set("style", original + suffix)
    facts, _, _, _, bridges = _read_disclosures(
        source, etree.tostring(root), check_deadline=_deadline
    )
    assert len(facts) == 16 and all(bridge.residual == 0 for bridge in bridges)


@pytest.mark.parametrize(
    "replacement,accepted",
    (
        ("f_488c65b3-e97c-456a-a919-0b3d8183dd75", False),
        ("F_488c65b3-e97c-456a-a919-0b3d8183dd75x", False),
        ("F_zz8c65b3-e97c-456a-a919-0b3d8183dd75", False),
        ("F_488c65b3-e97c-456a-a919-0b3d8183dd7", False),
        ("F_488c65b3-e97c-456a-a919-0b3d8183dd75", True),
    ),
)
def test_sec_caption_annotation_still_requires_the_finite_uuid_lexical_form(
    sources, replacement, accepted
):
    source = sources["historical"]
    root = _root(source)
    (annotation,) = root.xpath(
        '//*[local-name()="span" and contains(@style,"F_488c65b3-e97c-456a-a919-0b3d8183dd75")]'
    )
    annotation.set("style", "-sec-ix-hidden:" + replacement)
    if accepted:
        facts, _, _, _, bridges = _read_disclosures(
            source, etree.tostring(root), check_deadline=_deadline
        )
        assert len(facts) == 16 and all(bridge.residual == 0 for bridge in bridges)
    else:
        with pytest.raises(_Refusal) as rejected:
            _read_disclosures(source, etree.tostring(root), check_deadline=_deadline)
        assert rejected.value.reason == "unsupported_presentation"


@pytest.mark.parametrize(
    "namespace,name,prefix,refused",
    (
        (_HTML, "style", None, True),
        (_HTML, "STYLE", None, True),
        (_HTML, "Style", None, True),
        ("urn:unrelated", "style", None, True),
        ("urn:unrelated", "StYlE", None, True),
        (None, "STYLE", None, True),
        (_HTML, "link", None, True),
        (_HTML, "LiNk", None, True),
        ("urn:unrelated", "LINK", None, True),
        (_HTML, "script", None, True),
        (_HTML, "ScRiPt", None, True),
        ("urn:unrelated", "SCRIPT", None, True),
        (_HTML, "style", "html", True),
        (_HTML, "link", "html", True),
        (_HTML, "script", "html", True),
        ("http://www.w3.org/2000/svg", "style", "svg", True),
        ("http://www.w3.org/2000/svg", "script", "svg", True),
        ("urn:unrelated", "style", "chart", False),
        ("urn:unrelated", "STYLE", "chart", False),
        ("urn:unrelated", "link", "chart", False),
        ("urn:unrelated", "SCRIPT", "chart", False),
        ("http://www.w3.org/1999/XHTML", "style", "chart", False),
        ("urn:unrelated", "title", None, False),
        (_HTML, "title", None, False),
        ("urn:unrelated", "styler", None, False),
        ("urn:unrelated", "style", "STYLE", False),
    ),
)
def test_document_sources_follow_xml_qnames_and_unprefixed_html_ascii_tokens(
    sources, namespace, name, prefix, refused
):
    source = sources["historical"]
    root = _root(source)
    (body,) = root.iter("{" + _HTML + "}body")
    node = etree.Element(
        "{" + namespace + "}" + name if namespace is not None else name,
        nsmap={prefix: namespace} if namespace is not None else {None: ""},
    )
    node.text = "tr { display:flex !important; }"
    body.append(node)
    member = etree.tostring(root)
    if refused:
        with pytest.raises(_Refusal) as rejected:
            _read_disclosures(source, member, check_deadline=_deadline)
        assert rejected.value.reason == "unsupported_presentation"
    else:
        facts, zeros, link, _, bridges = _read_disclosures(
            source, member, check_deadline=_deadline
        )
        assert len(facts) == 16 and len(zeros) == 2
        assert link.from_refs == _ORIGINAL_ENDPOINTS
        assert all(bridge.residual == 0 for bridge in bridges)


@pytest.mark.parametrize("name", ("\u017ftyle", "scr\u0130pt", "l\u0131nk"))
def test_html_document_source_names_use_only_ascii_case_equivalence(sources, name):
    source = sources["historical"]
    root = _root(source)
    (body,) = root.iter("{" + _HTML + "}body")
    node = etree.SubElement(
        body, "{urn:unrelated}" + name, nsmap={None: "urn:unrelated"}
    )
    node.text = "tr { display:flex !important; }"
    facts, _, _, _, bridges = _read_disclosures(
        source, etree.tostring(root, encoding="utf-8"), check_deadline=_deadline
    )
    assert len(facts) == 16 and all(bridge.residual == 0 for bridge in bridges)
