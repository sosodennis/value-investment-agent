from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from fundamental_service.sec_ownership import (
    SecOwnershipEvidenceV1,
    SecOwnershipRequestV1,
    SecOwnershipSourceV1,
    inspect_sec_ownership_sources,
    parse_sec_ownership_source,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError

CIK = "0000724910"
ACCESSION = "0001167691-24-000001"
ACCEPTED = datetime(2024, 5, 1, 22, 52, 22, tzinfo=UTC)
CUTOFF = datetime(2025, 4, 1, tzinfo=UTC)


def submission(*, form="4", table=None, footnotes=None):
    if table is None:
        table = """<derivativeTable><derivativeTransaction>
<securityTitle><value>Incentive Stock Option</value></securityTitle>
<conversionOrExercisePrice><value>76.93</value></conversionOrExercisePrice>
<transactionDate><value>2024-05-01</value><footnoteId id="F1"/></transactionDate>
<transactionCoding><transactionCode>A</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>2500</value></transactionShares></transactionAmounts>
<postTransactionAmounts><sharesOwnedFollowingTransaction><value>12500</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
</derivativeTransaction></derivativeTable>"""
    if footnotes is None:
        footnotes = '<footnotes><footnote id="F1">Incentive stock option vested 05/01/2024 that was awarded 05/01/2023.</footnote></footnotes>'
    return f"""<SEC-DOCUMENT>{ACCESSION}.txt : 20240501
<SEC-HEADER>{ACCESSION}.hdr.sgml : 20240501
<ACCEPTANCE-DATETIME>20240501185222
ACCESSION NUMBER: {ACCESSION}
CONFORMED SUBMISSION TYPE: {form}
CONFORMED PERIOD OF REPORT: 20240429
FILED AS OF DATE: 20240501
DATE AS OF CHANGE: 20240501
REPORTING-OWNER:
    CENTRAL INDEX KEY: 0001167691
ISSUER:
    CENTRAL INDEX KEY: {CIK}
</SEC-HEADER>
<DOCUMENT>
<TYPE>{form}
<SEQUENCE>1
<FILENAME>primary_doc.xml
<TEXT>
<XML>
<?xml version="1.0"?>
<ownershipDocument><documentType>{form}</documentType>
<periodOfReport>2024-04-29</periodOfReport>
<issuer><issuerCik>{CIK}</issuerCik></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>0001167691</rptOwnerCik><rptOwnerName>Example</rptOwnerName></reportingOwnerId></reportingOwner>
{table}{footnotes}
<remarks>Source-only observations</remarks></ownershipDocument>
</XML>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
""".encode()


def source(raw, **changes):
    return SecOwnershipSourceV1.model_validate(
        {
            "accession_number": ACCESSION,
            "form": "4",
            "content_sha256": sha256(raw).hexdigest(),
            "accepted_at": ACCEPTED,
            "filing_date": date(2024, 5, 1),
            "captured_at": datetime(2026, 11, 13, tzinfo=UTC),
            **changes,
        }
    )


def parse(raw, **changes):
    return parse_sec_ownership_source(
        raw, issuer_id=CIK, valuation_at=CUTOFF, source=source(raw, **changes)
    )


def test_vesting_and_owner_totals_remain_verbatim_observations():
    raw = submission()
    first = parse(raw)
    second = parse(raw)

    assert canonical_bytes(first) == canonical_bytes(second)
    assert first.accepted_at == ACCEPTED  # Header is Eastern, not UTC.
    assert first.available_at == ACCEPTED
    assert first.period_of_report == date(2024, 4, 29)
    assert first.source_sha256 == sha256(raw).hexdigest()
    xml = raw.split(b"<XML>\n", 1)[1].split(b"</XML>", 1)[0]
    assert first.document_sha256 == sha256(xml).hexdigest()
    assert first.complete_inventory is False
    assert len(first.rows) == 1
    fields = {field.locator: field for field in first.rows[0].fields}
    prefix = "/ownershipDocument/derivativeTable/derivativeTransaction/"
    assert fields[prefix + "transactionAmounts/transactionShares/value"].text == "2500"
    assert (
        fields[
            prefix + "postTransactionAmounts/sharesOwnedFollowingTransaction/value"
        ].text
        == "12500"
    )
    assert fields[prefix + "transactionDate/footnoteId"].attributes == (("id", "F1"),)
    assert (
        first.footnotes[0].text
        == "Incentive stock option vested 05/01/2024 that was awarded 05/01/2023."
    )
    assert "grant_date" not in first.model_dump()


@pytest.mark.parametrize("form", ["3", "3/A", "4", "4/A", "5", "5/A"])
def test_originals_and_amendments_keep_their_own_identity(form):
    result = parse(submission(form=form), form=form)
    assert result.form == form
    assert (
        "SEC_OWNERSHIP_AMENDMENT_REQUIRES_RECONCILIATION" in result.issue_codes
    ) == form.endswith("/A")
    assert result.complete_inventory is False


def test_no_derivative_rows_are_missing_evidence_not_zero_inventory():
    raw = submission(
        table="<nonDerivativeTable><nonDerivativeHolding><securityTitle><value>Common</value></securityTitle></nonDerivativeHolding></nonDerivativeTable>",
        footnotes="",
    )
    result = parse(raw)
    assert len(result.rows) == 1
    assert result.rows[0].kind == "nonDerivativeHolding"
    assert result.issue_codes == ("SEC_OWNERSHIP_NO_DERIVATIVE_ROWS",)
    assert result.complete_inventory is False


@pytest.mark.parametrize(
    "before,after",
    [
        (b"<issuerCik>0000724910", b"<issuerCik>0000724911"),
        (b"CENTRAL INDEX KEY: 0000724910", b"CENTRAL INDEX KEY: 0000724911"),
        (b"<rptOwnerCik>0001167691", b"<rptOwnerCik>0001167692"),
        (b"<documentType>4", b"<documentType>5"),
        (b"<periodOfReport>2024-04-29", b"<periodOfReport>2024-04-30"),
        (b'<footnoteId id="F1"', b'<footnoteId id="missing"'),
        (b"</footnotes>", b'<footnote id="F1">duplicate</footnote></footnotes>'),
        (
            b"<ownershipDocument>",
            b'<!DOCTYPE ownershipDocument [<!ENTITY private SYSTEM "file:///private/never-read">]><ownershipDocument>',
        ),
        (b"<remarks>Source-only observations", b"<remarks>&undeclared;"),
        (b"</ownershipDocument>", b"</ownershipDocument><ownershipDocument/>"),
        (b"<TYPE>4", b"<TYPE>5"),
        (b"</DOCUMENT>\n", b""),
        (b"</SEC-DOCUMENT>\n", b""),
        (b"<TYPE>4\n", b"<TYPE>4\n<TYPE>5\n"),
        (
            b"<ACCEPTANCE-DATETIME>20240501185222",
            b"<ACCEPTANCE-DATETIME>20240501185222\n<ACCEPTANCE-DATETIME>20240501185222",
        ),
        (b"20240501185222", b"20241103013000"),
        (b"<derivativeTransaction>", b"<unknownRow>"),
    ],
)
def test_malformed_conflicting_or_unsafe_originals_are_refused(before, after):
    with pytest.raises(SnapshotError, match="ownership") as raised:
        parse(submission().replace(before, after))
    assert raised.value.code == "SEC_OWNERSHIP_SOURCE_INVALID"


def test_duplicate_primary_documents_are_ambiguous():
    raw = submission()
    document = (
        b"<DOCUMENT>" + raw.split(b"<DOCUMENT>", 1)[1].split(b"</SEC-DOCUMENT>", 1)[0]
    )
    with pytest.raises(SnapshotError):
        parse(raw.replace(b"</SEC-DOCUMENT>", document + b"</SEC-DOCUMENT>"))


def test_future_original_cannot_supply_an_earlier_decision():
    raw = submission()
    with pytest.raises(SnapshotError) as raised:
        parse_sec_ownership_source(
            raw,
            issuer_id=CIK,
            valuation_at=ACCEPTED.replace(hour=21),
            source=source(raw),
        )
    assert raised.value.code == "SEC_OWNERSHIP_NOT_AVAILABLE"


def test_corrected_header_uses_conservative_later_availability():
    raw = (
        submission()
        .replace(b".txt : 20240501", b".txt : 20240502")
        .replace(b".hdr.sgml : 20240501", b".hdr.sgml : 20240502")
        .replace(b"DATE AS OF CHANGE: 20240501", b"DATE AS OF CHANGE: 20240502")
    )
    assert parse(raw).available_at == datetime(2024, 5, 3, 4, tzinfo=UTC)
    with pytest.raises(SnapshotError) as raised:
        parse_sec_ownership_source(
            raw,
            issuer_id=CIK,
            valuation_at=datetime(2024, 5, 2, 23, tzinfo=UTC),
            source=source(raw),
        )
    assert raised.value.code == "SEC_OWNERSHIP_NOT_AVAILABLE"


def test_later_envelope_dates_do_not_erase_valid_historical_observations():
    raw = (
        submission()
        .replace(b".txt : 20240501", b".txt : 20240502")
        .replace(b".hdr.sgml : 20240501", b".hdr.sgml : 20240502")
    )
    result = parse(raw)
    assert result.filing_date == result.changed_date == date(2024, 5, 1)
    assert result.document_date == result.header_date == date(2024, 5, 2)
    assert result.accepted_at == ACCEPTED
    assert result.available_at == datetime(2024, 5, 3, 4, tzinfo=UTC)
    assert result.issue_codes == ("SEC_OWNERSHIP_LATER_HEADER_AVAILABILITY",)
    assert len(result.rows) == 1
    with pytest.raises(SnapshotError) as raised:
        parse_sec_ownership_source(
            raw,
            issuer_id=CIK,
            valuation_at=datetime(2024, 5, 2, 23, tzinfo=UTC),
            source=source(raw),
        )
    assert raised.value.code == "SEC_OWNERSHIP_NOT_AVAILABLE"


def test_envelope_dates_earlier_than_change_date_remain_conflicting():
    raw = submission().replace(b".txt : 20240501", b".txt : 20240430")
    with pytest.raises(SnapshotError) as raised:
        parse(raw)
    assert raised.value.code == "SEC_OWNERSHIP_SOURCE_INVALID"


def test_source_manifest_cannot_rewrite_hash_time_or_accession():
    raw = submission()
    for changes in (
        {"content_sha256": "f" * 64},
        {"accepted_at": CUTOFF},
        {"accession_number": "0001167691-24-000002"},
        {"filing_date": date(2024, 5, 2)},
        {"captured_at": datetime(2024, 4, 1, tzinfo=UTC)},
    ):
        with pytest.raises(SnapshotError):
            parse(raw, **changes)


def test_batch_retains_missing_conflicting_and_future_sources_on_repeat(tmp_path):
    store = FilesystemContentStore(tmp_path / "content")
    raw = submission()
    store.put(raw, media_type="text/plain")
    sources = (
        source(raw),
        source(raw, accession_number="0001167691-24-000002", content_sha256="a" * 64),
        source(raw, accession_number="0001167691-24-000003"),
        source(
            raw,
            accession_number="0001167691-24-000004",
            accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    request = SecOwnershipRequestV1(
        source_revision="a" * 40, issuer_id=CIK, valuation_at=CUTOFF, sources=sources
    )
    first = inspect_sec_ownership_sources(request, content=store)
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    second = inspect_sec_ownership_sources(
        request, content=FilesystemContentStore(tmp_path / "content")
    )
    assert first == second
    assert first.input_digest == sha256_digest(request)
    assert first.output_digest == sha256_digest(first.results)
    assert [r.status for r in first.results] == [
        "parsed",
        "refused",
        "refused",
        "refused",
    ]
    assert first.results[1].issue_codes == ("SOURCE_BYTES_UNAVAILABLE",)
    assert first.results[2].issue_codes == ("SEC_OWNERSHIP_SOURCE_INVALID",)
    assert first.mapping_approved is False
    assert first.complete_inventory is False
    assert first.supported_history_threshold is None
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }


def test_manifest_does_not_drop_or_reorder_duplicate_accessions():
    raw = submission()
    with pytest.raises(ValueError, match="ordered and distinct"):
        SecOwnershipRequestV1(
            source_revision="a" * 40,
            issuer_id=CIK,
            valuation_at=CUTOFF,
            sources=(source(raw), source(raw)),
        )


def test_future_source_refusal_is_retained_by_the_batch(tmp_path):
    raw = submission()
    content = FilesystemContentStore(tmp_path)
    content.put(raw, media_type="text/plain")
    request = SecOwnershipRequestV1(
        source_revision="a" * 40,
        issuer_id=CIK,
        valuation_at=ACCEPTED.replace(hour=21),
        sources=(source(raw),),
    )
    result = inspect_sec_ownership_sources(request, content=content)
    assert result.results[0].status == "refused"
    assert result.results[0].source == request.sources[0]
    assert result.results[0].issue_codes == ("SEC_OWNERSHIP_NOT_AVAILABLE",)


def test_serialized_evidence_rejects_dropped_sources_and_changed_digests(tmp_path):
    raw = submission()
    content = FilesystemContentStore(tmp_path)
    content.put(raw, media_type="text/plain")
    request = SecOwnershipRequestV1(
        source_revision="a" * 40,
        issuer_id=CIK,
        valuation_at=CUTOFF,
        sources=(source(raw),),
    )
    evidence = inspect_sec_ownership_sources(request, content=content)
    assert (
        SecOwnershipEvidenceV1.model_validate_json(canonical_bytes(evidence))
        == evidence
    )
    for change in (
        {"results": []},
        {"input_digest": "f" * 64},
        {"output_digest": "f" * 64},
        {"complete_inventory": True},
        {"mapping_approved": True},
    ):
        with pytest.raises(ValueError):
            SecOwnershipEvidenceV1.model_validate_json(
                canonical_bytes({**evidence.model_dump(), **change})
            )


@pytest.fixture
def inspection_command(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    import inspect_sec_ownership

    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    monkeypatch.setattr(inspect_sec_ownership, "ROOT", repository)
    raw = submission()
    store = FilesystemContentStore(tmp_path / "content")
    store.put(raw, media_type="text/plain")
    request = SecOwnershipRequestV1(
        source_revision=head, issuer_id=CIK, valuation_at=CUTOFF, sources=(source(raw),)
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(canonical_bytes(request))
    output = tmp_path / "reports"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inspect_sec_ownership.py",
            "--manifest",
            str(manifest),
            "--content-root",
            str(store.root),
            "--output-directory",
            str(output),
        ],
    )
    return inspect_sec_ownership.main, repository, manifest, output


def test_operator_command_reuses_the_actual_report_without_rewriting(
    inspection_command, capsys
):
    command, _, _, output = inspection_command
    assert command() == 0
    first = json.loads(capsys.readouterr().out)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()}
    assert command() == 0
    second = json.loads(capsys.readouterr().out)
    assert first["wrote"] is True and second["wrote"] is False
    assert first["report_digest"] == second["report_digest"]
    assert first["input_digest"] == second["input_digest"]
    assert first["output_digest"] == second["output_digest"]
    assert first["parsed"] == 1 and first["refused"] == 0
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()
    }


@pytest.mark.parametrize("change", ["untracked", "wrong_commit", "inside_checkout"])
def test_operator_command_refuses_unreviewed_state_before_publication(
    inspection_command, capsys, monkeypatch, change
):
    command, repository, manifest, output = inspection_command
    if change == "untracked":
        (repository / "unreviewed.py").write_text("source = 'not committed'\n")
    elif change == "wrong_commit":
        value = json.loads(manifest.read_bytes())
        value["source_revision"] = "0" * 40
        manifest.write_bytes(canonical_bytes(value))
    else:
        output = repository / "generated"
        monkeypatch.setattr(sys, "argv", [*sys.argv[:-1], str(output)])
    assert command() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert not output.exists()
