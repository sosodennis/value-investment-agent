import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import html


FIXTURES = Path(__file__).parent / "fixtures/annual-statements"
COHORT = json.loads((FIXTURES / "issue494-cohort.json").read_text())
GOLDEN = json.loads((FIXTURES / "issue494-golden.json").read_text())
BOUNDARIES = json.loads((FIXTURES / "issue494-boundary-cases.json").read_text())


def test_cohort_retains_five_originals_at_both_cutoffs_without_valuation_threshold():
    assert COHORT["history_coverage_target"] == 5
    assert COHORT["supported_history_threshold"] is None
    originals = {row["accession_number"]: row for row in COHORT["filings"]}
    assert len(originals) == 14
    for case in COHORT["cases"]:
        assert len(case["requested_years"]) == 5
        assert len(set(case["original_accessions"])) == 5
        assert case["validation_state_at_freeze"] == "not_run"
        cutoff = datetime.fromisoformat(case["cutoff_at"])
        for accession in case["original_accessions"]:
            original = originals[accession]
            assert original["issuer_id"] == case["issuer_id"]
            assert datetime.fromisoformat(original["accepted_at"]) <= cutoff
    current = [case for case in COHORT["cases"] if case["case_id"].endswith("current")]
    assert len(current) == 2
    assert all(case["requested_years"] == list(range(2022, 2027)) for case in current)


def test_cohort_binds_new_original_receipts_without_claiming_validation_success():
    for filing in COHORT["filings"]:
        assert filing["expected_source_result"] == (
            "major_rows_available_after_formal_validation_and_mapping"
        )
        assert filing["validation_state_at_freeze"] == "not_run"
        sources = filing["source_records"]
        assert len(sources) == 4
        assert all(len(source["content_hash"]) == 64 for source in sources)
        assert all(source["http_status"] == 200 for source in sources)
        assert any(source["uri"].endswith("-xbrl.zip") for source in sources)
        assert any(source["uri"].endswith(".txt") for source in sources)
        assert any(source["uri"].endswith("index.json") for source in sources)
        assert (
            filing["required_validation"]["exact_us_gaap_namespace"]
            == (filing["taxonomy_namespaces"]["us-gaap"])
        )


def _rows(filing):
    return {
        row["row_id"]: row
        for statement in filing["statements"]
        for row in statement["rows"]
    }


@pytest.mark.parametrize(
    "filing", GOLDEN["filings"], ids=lambda row: row["accession_number"]
)
def test_independent_golden_preserves_major_rows_and_reconciles_reported_totals(filing):
    rows = _rows(filing)
    assert set(rows) == {
        row for statement in COHORT["supported_rows"].values() for row in statement
    }
    values = {
        key: Decimal(row["values"][0]["value"])
        for key, row in rows.items()
        if row["status"] == "reported"
    }
    assert values["revenue"] - values["cost_of_revenue"] == values["gross_profit"]
    assert (
        values["income_before_tax"] - values["income_tax_expense"]
        == values["net_income"]
    )
    assert (
        values["total_assets"] == values["total_liabilities"] + values["total_equity"]
    )
    assert values["liabilities_and_equity"] == values["total_assets"]
    assert (
        values["cash_flow_beginning_balance"] + values["net_change_in_cash"]
        == (values["cash_flow_ending_balance"])
    )
    subtotal = sum(
        values[key]
        for key in ("operating_cash_flow", "investing_cash_flow", "financing_cash_flow")
    )
    if filing["issuer_id"] == "0000320193":
        assert rows["effect_of_exchange_rates_on_cash"]["status"] == "missing"
        assert subtotal == values["net_change_in_cash"]
        full_check = next(
            check
            for check in filing["reconciliation_expectations"]
            if check["check_id"] == "cash_activity_rollforward_with_fx"
        )
        assert full_check["status"] == "unresolved"
    else:
        assert (
            subtotal + values["effect_of_exchange_rates_on_cash"]
            == values["net_change_in_cash"]
        )


def test_apple_comparatives_preserve_52_and_53_weeks_and_cash_definition():
    filing = next(
        row
        for row in GOLDEN["filings"]
        if row["accession_number"] == "0000320193-24-000123"
    )
    rows = _rows(filing)
    periods = [value["source_period"] for value in rows["revenue"]["values"]]
    assert [
        (
            date.fromisoformat(period["end_date"])
            - date.fromisoformat(period["start_date"])
        ).days
        + 1
        for period in periods
    ] == [364, 371, 364]
    assert [value["value"] for value in rows["revenue"]["values"]] == [
        "391035000000",
        "383285000000",
        "394328000000",
    ]
    assert rows["cash_and_equivalents"]["values"][1]["value"] == "29965000000"
    assert rows["cash_flow_ending_balance"]["values"][1]["value"] == "30737000000"


def _local_name(element):
    return element.tag.lower().split(":")[-1] if isinstance(element.tag, str) else ""


def _text(element):
    return " ".join(element.text_content().split())


def _content(root, source):
    suffix = ".json" if source["media_type"] == "application/json" else ".bin"
    path = (
        root
        / "content"
        / source["content_hash"][:2]
        / (source["content_hash"] + suffix)
    )
    payload = path.read_bytes()
    assert len(payload) == source["received_size"]
    assert hashlib.sha256(payload).hexdigest() == source["content_hash"]
    return payload


@pytest.fixture(scope="module")
def retained_root():
    configured = os.getenv("ISSUE494_SEC_EVIDENCE_DIR")
    if configured is None:
        pytest.skip("set ISSUE494_SEC_EVIDENCE_DIR to verify frozen original bytes")
    return Path(configured)


@pytest.mark.parametrize(
    "filing", GOLDEN["filings"], ids=lambda row: row["accession_number"]
)
def test_golden_matches_retained_original_primary_statement_without_production_parser(
    filing, retained_root
):
    records = {
        record["artifact_id"]: record
        for line in (retained_root / "artifacts/.artifact-records.jsonl")
        .read_text()
        .splitlines()
        if (record := json.loads(line))
    }
    original = next(
        row
        for row in COHORT["filings"]
        if row["accession_number"] == filing["accession_number"]
    )
    sources = original["source_records"]
    for source in sources:
        _content(retained_root, source)
        assert source["receipt_refs"]
        for reference in source["receipt_refs"]:
            record = records[reference["artifact_id"]]
            assert record["content_hash"] == reference["content_hash"]
            assert record["status"] == "valid"
            assert source["content_hash"] in record["dependency_hashes"]
            payload = (retained_root / reference["retained_path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == reference["content_hash"]
            receipt = json.loads(payload)
            assert receipt["schema_version"] == reference["schema_version"]
            assert receipt["scope"] == reference["scope"]
            assert receipt["scope"]["cik"] == filing["issuer_id"]
            assert receipt["scope"]["accession_number"] == filing["accession_number"]
            assert all(
                receipt[key] == value
                for key, value in source.items()
                if key != "receipt_refs"
            )
    raw = next(source for source in sources if source["uri"].endswith(".htm"))
    assert raw["content_hash"] == filing["source_sha256"]
    document = html.fromstring(_content(retained_root, raw))
    contexts = {
        element.get("id"): element
        for element in document.iter()
        if _local_name(element) == "context"
    }
    units = {
        element.get("id"): element
        for element in document.iter()
        if _local_name(element) == "unit"
    }
    for statement in filing["statements"]:
        table = document.xpath("//table")[statement["table_index"]]
        for row in statement["rows"]:
            if row["status"] != "reported":
                assert not any(
                    "EffectOfExchangeRate" in element.get("name", "")
                    for element in table.iter()
                )
                continue
            raw_row = table.xpath("./tbody/tr|./tr")[row["row_index"]]
            assert _text(next(raw_row.iterchildren())) == row["printed_row_label"]
            facts = [
                element
                for element in raw_row.iter()
                if _local_name(element) == "nonfraction"
            ]
            for expected in row["values"]:
                fact = facts[expected["fact_index"]]
                assert fact.get("name") == expected["concept_qname"]
                assert fact.get("contextref") == expected["context_id"]
                assert fact.get("unitref") == expected["unit_ref"]
                assert fact.get("scale") == str(expected["scale"])
                assert fact.get("sign") == expected["sign"]
                assert fact.get("decimals") == expected["decimals"]
                assert _text(fact) == expected["lexical_value"]
                lexical = _text(fact).replace(",", "").replace(" ", "")
                value = Decimal(0) if lexical in {"—", "–", "-"} else Decimal(lexical)
                if fact.get("sign") == "-":
                    value = -value
                assert value * Decimal(10) ** expected["scale"] == Decimal(
                    expected["value"]
                )
                context = contexts[expected["context_id"]]
                assert not any(
                    _local_name(element) in {"explicitmember", "typedmember"}
                    for element in context.iter()
                )
                identifiers = [
                    element
                    for element in context.iter()
                    if _local_name(element) == "identifier"
                ]
                assert _text(identifiers[0]) == expected["entity_identifier"]
                period = expected["source_period"]
                dates = {
                    _local_name(element): _text(element)
                    for element in context.iter()
                    if _local_name(element) in {"startdate", "enddate", "instant"}
                }
                if period["period_type"] == "duration":
                    assert dates == {
                        "startdate": period["start_date"],
                        "enddate": period["end_date"],
                    }
                else:
                    assert dates == {"instant": period["instant"]}
                measure = next(
                    element
                    for element in units[expected["unit_ref"]].iter()
                    if _local_name(element) == "measure"
                )
                assert _text(measure) == expected["unit_measure"]


def test_boundary_zero_dimension_and_custom_observations_exist_in_raw_source(
    retained_root,
):
    cases = {case["case_id"]: case for case in BOUNDARIES["cases"]}
    originals = {row["accession_number"]: row for row in COHORT["filings"]}
    zero = cases["reported-zero"]
    original = originals[zero["accession_number"]]
    source = next(
        row for row in original["source_records"] if row["uri"].endswith(".htm")
    )
    document = html.fromstring(_content(retained_root, source))
    row = document.xpath("//table")[zero["table_index"]].xpath("./tbody/tr|./tr")[
        zero["row_index"]
    ]
    fact = [node for node in row.iter() if _local_name(node) == "nonfraction"][
        zero["fact_index"]
    ]
    assert _text(fact) == zero["lexical_value"] == "0"
    assert fact.get("name") == zero["concept_qname"]
    assert fact.get("contextref") == zero["source_context_id"]

    original = originals["0000320193-24-000123"]
    source = next(
        row for row in original["source_records"] if row["uri"].endswith(".htm")
    )
    document = html.fromstring(_content(retained_root, source))
    for key in ("dimension-is-not-consolidated-total", "unapproved-custom-concept"):
        case = cases[key]
        fact = document.xpath("//*[@id=$id]", id=case["source_inline_id"])[0]
        assert fact.get("name") == case["concept_qname"]
        assert fact.get("contextref") == case["source_context_id"]
        if key == "dimension-is-not-consolidated-total":
            context = document.xpath("//*[@id=$id]", id=case["source_context_id"])[0]
            dimension = next(
                node for node in context.iter() if _local_name(node) == "explicitmember"
            )
            assert dimension.get("dimension") == case["dimension"]["axis"]
            assert _text(dimension) == case["dimension"]["member"]


def test_boundary_expectations_distinguish_original_failures_and_synthetic_mutations():
    cases = {case["case_id"]: case for case in BOUNDARIES["cases"]}
    assert (
        cases["tesla-original-missing-dts"]["expected"]["parse_only_fact_count"] == 276
    )
    assert (
        cases["tesla-amendment-missing-dts"]["expected"]["parse_only_fact_count"] == 0
    )
    assert (
        cases["tesla-original-missing-dts"]["expected"]["canonical_qualification"]
        == "refused"
    )
    assert cases["part-iii-amendment-unknown-scope"]["amendment_scope"] == "unknown"
    assert (
        cases["part-iii-amendment-unknown-scope"]["amends_accession"]
        == "0001628280-25-003063"
    )
    assert cases["reported-zero"]["expected"]["value"] == "0"
    assert cases["reported-negative"]["expected"]["value"] == "-121983000000"
    assert cases["fx-not-separately-presented"]["expected"]["status"] == "missing"
    assert cases["present-but-unparsed"]["expected"]["status"] == "error"
    assert cases["purpose-unconfirmed"]["expected"]["status"] == "unresolved"
    assert cases["non-applicable-row"]["expected"]["status"] == "not_applicable"
    for case_id in (
        "equal-precision-conflict",
        "present-but-unparsed",
        "non-applicable-row",
    ):
        assert cases[case_id]["synthetic"] is True
