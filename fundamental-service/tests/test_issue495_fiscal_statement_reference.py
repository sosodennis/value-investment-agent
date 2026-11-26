from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest

FIXTURES = Path(__file__).parent / "fixtures/quarterly-statements"
SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/reproduce_fiscal_statement_sources.py"
)
spec = importlib.util.spec_from_file_location("issue495_reference", SCRIPT)
assert spec and spec.loader
reference = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reference
spec.loader.exec_module(reference)

BOUNDARIES = json.loads((FIXTURES / "issue495-boundary-cases.json").read_bytes())
REVENUE = {
    "row_id": "revenue",
    "statement": "income_statement",
    "aggregation": "additive_flow",
}
ASSETS = {
    "row_id": "total_assets",
    "statement": "balance_sheet",
    "aggregation": "period_end_instant",
}
OPENING = {
    "row_id": "cash_flow_beginning_balance",
    "statement": "cash_flow",
    "aggregation": "cash_flow_boundary",
}
CLOSING = {
    "row_id": "cash_flow_ending_balance",
    "statement": "cash_flow",
    "aggregation": "cash_flow_boundary",
}
NET_CHANGE = {
    "row_id": "net_change_in_cash",
    "statement": "cash_flow",
    "aggregation": "additive_flow",
}
ROWS = [REVENUE, ASSETS, OPENING, CLOSING, NET_CHANGE]
CASE = {
    "case_id": "synthetic",
    "issuer_id": BOUNDARIES["issuer_id"],
    "cutoff_at": BOUNDARIES["cutoff_at"],
}


def make_fact(
    observation_id: str,
    end_date: str,
    value: str,
    *,
    start_date: str = BOUNDARIES["fiscal_year_start"],
    row_id: str = "revenue",
    roles: list[str] | None = None,
    decimals: str = "INF",
    accepted_at: str = BOUNDARIES["accepted_at"],
    form: str = "10-Q",
) -> reference.Fact:
    del roles
    return reference.Fact(
        observation_id=observation_id,
        row_id=row_id,
        statement="income_statement",
        issuer_id=CASE["issuer_id"],
        accession_number="synthetic",
        form=form,
        filing_date=accepted_at[:10],
        accepted_at=accepted_at,
        report_date=end_date,
        primary_document="synthetic.htm",
        primary_html_sha256="0" * 64,
        qname="us-gaap:" + row_id,
        namespace_uri="http://fasb.org/us-gaap/2024",
        context_id="synthetic/" + observation_id,
        entity_identifier=CASE["issuer_id"],
        entity_scheme="http://www.sec.gov/CIK",
        period={
            "period_type": "duration",
            "start_date": start_date,
            "end_date": end_date,
        },
        dimensions=(),
        unit_ref="usd",
        unit_measures=("iso4217:USD",),
        raw_text=value,
        value=Decimal(value),
        numeric_error=None,
        scale=None,
        sign=None,
        decimals=decimals,
        format_name=None,
        table_index=0,
        row_index=0,
        printed_row_label=row_id,
        fact_index=0,
    )


def base_facts() -> list[reference.Fact]:
    return [make_fact(**fact) for fact in BOUNDARIES["flow_observations"]]


def base_periods() -> list[dict[str, object]]:
    return [
        {**period, "accession_number": "synthetic"} for period in BOUNDARIES["quarters"]
    ]


def quarter_cells(facts: list[reference.Fact]) -> list[dict[str, object]]:
    parsed = reference.ParsedFiling(
        {"reported_period_end": "2024-06-30"}, {}, {"revenue": facts}, {}, {}, {}
    )
    return [
        reference.build_quarter_cell(
            REVENUE,
            period,
            BOUNDARIES["fiscal_year_start"],
            None if index == 0 else BOUNDARIES["quarters"][index - 1]["end_date"],
            {"synthetic": parsed},
            CASE,
            {},
        )
        for index, period in enumerate(base_periods())
    ]


def ttm_result(
    periods: list[dict[str, object]],
    cells: list[dict[str, object]],
    rows: list[dict[str, object]],
    observations: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    result = reference.build_ttm_golden(
        [{**CASE, "quarter_periods": periods, "cells": cells}],
        rows,
        {CASE["case_id"]: observations},
    )
    windows = reference.records(result["windows"])
    assert len(windows) == 1
    return {
        str(cell["row_id"]): cell for cell in reference.records(windows[0]["cells"])
    }


def base_ttm_inputs() -> tuple[
    list[dict[str, object]], list[dict[str, object]], dict[str, dict[str, object]]
]:
    facts = base_facts()
    periods = base_periods()
    cells = quarter_cells(facts)
    for index, period in enumerate(periods):
        start = str(period["start_date"])
        end = str(period["end_date"])
        for row in ROWS[1:]:
            row_id = row["row_id"]
            fact_id = f"{period['quarter_id']}/{row_id}"
            value = {
                ASSETS["row_id"]: str(610 + index * 100),
                OPENING["row_id"]: str(25 + index * 10),
                CLOSING["row_id"]: str(35 + index * 10),
                NET_CHANGE["row_id"]: "10",
            }[row_id]
            fact = make_fact(fact_id, end, value, start_date=start, row_id=row_id)
            if row != NET_CHANGE:
                instant = (
                    (date.fromisoformat(start) - timedelta(days=1)).isoformat()
                    if row == OPENING
                    else end
                )
                concept = "us-gaap:cash" if row in (OPENING, CLOSING) else fact.qname
                fact = replace(
                    fact,
                    period={"period_type": "instant", "instant": instant},
                    qname=concept,
                )
            facts.append(fact)
            cells.append(
                {
                    "cell_id": fact_id,
                    "row_id": row_id,
                    "end_date": end,
                    "availability": "reported"
                    if row == NET_CHANGE
                    else "reported_instant",
                    "value": value,
                    "selected_observation_ids": [fact_id],
                    "unit_measures": ["iso4217:USD"],
                    "precision_interval": reference.fact_interval_json(fact),
                }
            )
    return periods, cells, {fact.observation_id: fact.json() for fact in facts}


def test_base_proves_q1_q2_q3_q4_and_ttm():
    cells = quarter_cells(base_facts())
    for cell, expected in zip(
        cells, BOUNDARIES["base_expectations"]["quarters"], strict=True
    ):
        assert_observed(cell, expected)
    assert cells[0]["observation_roles"] == ["reported_quarter", "same_span_ytd"]
    periods, cells, observations = base_ttm_inputs()
    result = ttm_result(periods, cells, ROWS, observations)
    assert_observed(result["revenue"], BOUNDARIES["base_expectations"]["ttm"])
    assert [
        result[row["row_id"]]["value"] for row in (ASSETS, OPENING, CLOSING, NET_CHANGE)
    ] == ["910", "25", "65", "40"]
    assert (
        result[OPENING["row_id"]]["cash_rollforward_reconciliation"]["status"]
        == "intervals_overlap"
    )


def test_crosschecked_quarter_waits_for_actual_prior_ytd():
    direct = make_fact("q2_direct", "2023-12-31", "110", start_date="2023-10-01")
    late = "2024-07-31T18:00:00Z"

    def q2_cell(prior_time):
        rows = [{**REVENUE, "row_id": f"synthetic_flow_{index}"} for index in range(25)]
        facts_by_row = {
            row["row_id"]: [
                replace(
                    fact,
                    row_id=row["row_id"],
                    observation_id=f"{row['row_id']}/{fact.observation_id}",
                    accepted_at=prior_time
                    if fact.observation_id == "q1"
                    else fact.accepted_at,
                )
                for fact in [*base_facts(), direct]
            ]
            for row in rows
        }
        observations = {
            fact.observation_id: fact.json()
            for facts in facts_by_row.values()
            for fact in facts
        }
        periods = [
            {
                **period,
                "fiscal_year_start": BOUNDARIES["fiscal_year_start"],
                "prior_quarter_end": base_periods()[index - 1]["end_date"]
                if index
                else None,
            }
            for index, period in enumerate(base_periods())
        ]
        parsed = reference.ParsedFiling(
            {"reported_period_end": "2024-06-30"}, {}, facts_by_row, {}, {}, {}
        )
        golden = reference.build_case_golden(
            CASE, periods * 2, {"synthetic": parsed}, rows, observations
        )
        cell = golden["cells"][25]
        assert cell["value"] == "110"
        assert cell["availability"] == "reported_with_derived_crosscheck"
        assert (
            observations[cell["selected_observation_ids"][0]]["accepted_at"]
            == direct.accepted_at
        )
        return cell["source_available_at"]

    assert q2_cell(direct.accepted_at) == direct.accepted_at
    assert q2_cell(late) == late


def assert_observed(actual: dict, expected: dict) -> None:
    expected = dict(expected)
    if reason := expected.pop("rejection_reason", None):
        rejected = actual["selection_decision"]["direct"]["rejected_candidates"]
        assert any(reason in candidate["reasons"] for candidate in rejected)
    assert {key: actual[key] for key in expected} == expected


@pytest.mark.parametrize(
    "boundary",
    [case for case in BOUNDARIES["cases"] if case["operation"] == "quarter"],
    ids=lambda case: case["id"],
)
def test_quarter_boundaries(boundary):
    facts = base_facts()
    mutation = deepcopy(boundary["mutation"])
    if observed := mutation.get("remove_fact"):
        facts = [fact for fact in facts if fact.observation_id != observed]
    elif addition := mutation.get("add_fact"):
        if addition.pop("withhold_ytd", False):
            facts = [fact for fact in facts if fact.observation_id != "q2_ytd"]
        facts.append(make_fact(**addition))
    elif mutation.get("add_conflicting_direct"):
        facts.append(make_fact("direct", "2023-12-31", "110", start_date="2023-10-01"))
        facts.append(
            make_fact("direct_conflict", "2023-12-31", "180", start_date="2023-10-01")
        )
    else:
        attribute = mutation["field"]
        value = (
            Decimal(mutation["value"]) if attribute == "value" else mutation["value"]
        )
        facts = [
            replace(fact, **{attribute: value})
            if fact.observation_id == mutation["fact"]
            else fact
            for fact in facts
        ]
    cell = quarter_cells(facts)[int(boundary["target"][-1]) - 1]
    assert_observed(cell, boundary["expected"])


@pytest.mark.parametrize(
    "boundary",
    [case for case in BOUNDARIES["cases"] if case["operation"] == "ttm"],
    ids=lambda case: case["id"],
)
def test_ttm_boundaries(boundary):
    periods, cells, observations = base_ttm_inputs()
    mutation = boundary["mutation"]
    if missing := mutation.get("remove_period"):
        periods = [period for period in periods if period["quarter_id"] != missing]
    elif target_period := mutation.get("period"):
        period = next(
            period for period in periods if period["quarter_id"] == target_period
        )
        period[mutation["field"]] = mutation["value"]
    elif swapped := mutation.get("swap_periods"):
        left, right = swapped
        periods[left], periods[right] = periods[right], periods[left]
    elif missing_cell := mutation.get("remove_cell"):
        quarter, row_id = missing_cell.split("/")
        end = next(
            period["end_date"] for period in periods if period["quarter_id"] == quarter
        )
        cells = [
            cell
            for cell in cells
            if (cell["end_date"], cell["row_id"]) != (end, row_id)
        ]
    elif observed := mutation.get("observation"):
        observations[observed][mutation["field"]] = mutation["value"]
    else:
        raise AssertionError(f"Unknown TTM boundary mutation: {mutation}")
    if boundary["expected"]["availability"] == "rejected":
        with pytest.raises(
            ValueError, match=f"^{re.escape(boundary['expected']['outcome_code'])}$"
        ):
            ttm_result(periods, cells, ROWS, observations)
        return
    result = ttm_result(periods, cells, ROWS, observations)
    assert_observed(result[boundary.get("target", "revenue")], boundary["expected"])


@pytest.mark.parametrize(
    "boundary",
    [case for case in BOUNDARIES["cases"] if case["operation"] == "ttm_non_additive"],
    ids=lambda case: case["id"],
)
def test_ttm_non_additive_observations_are_unsupported(boundary: dict) -> None:
    periods, cells, observations = base_ttm_inputs()
    row = boundary["row"]
    row_id = row["row_id"]
    for period, value in zip(periods, boundary["quarter_values"], strict=True):
        quarter_id = period["quarter_id"]
        observation_id = f"synthetic/{row_id}/{quarter_id}"
        fact = replace(
            make_fact(
                observation_id,
                str(period["end_date"]),
                value,
                start_date=str(period["start_date"]),
                row_id=row_id,
                form="10-K" if quarter_id == "q4" else "10-Q",
            ),
            qname=boundary["qname"],
            namespace_uri=boundary["namespace_uri"],
            context_id=f"synthetic_{quarter_id}",
            unit_ref=boundary["unit_ref"],
            unit_measures=tuple(boundary["unit_measures"]),
        )
        observations[observation_id] = fact.json()
        cells.append(
            {
                "cell_id": observation_id,
                "row_id": row_id,
                "end_date": period["end_date"],
                "availability": "reported",
                "value": value,
                "selected_observation_ids": [observation_id],
                "unit_measures": list(fact.unit_measures),
                "precision_interval": reference.fact_interval_json(fact),
            }
        )

    result = ttm_result(periods, cells, [*ROWS, row], observations)
    assert_observed(result[row_id], boundary["expected"])


def put_response(
    root: Path, uri: str, payload: bytes, cik: str = CASE["issuer_id"]
) -> tuple[dict[str, object], Path]:
    accession = "0000000000-24-000001"
    content_hash = hashlib.sha256(payload).hexdigest()
    media_type = "application/json" if uri.endswith("/index.json") else "text/html"
    suffix = ".json" if media_type == "application/json" else ".bin"
    path = root / "content" / content_hash[:2] / (content_hash + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "uri": uri,
        "content_hash": content_hash,
        "media_type": media_type,
        "received_size": len(payload),
        "scope": {"cik": cik, "accession_number": accession},
    }, path


@pytest.mark.parametrize(
    "boundary",
    [
        case
        for case in BOUNDARIES["cases"]
        if case["operation"] in {"source", "parse_filing"}
    ],
    ids=lambda case: case["id"],
)
def test_source_and_parser_boundaries(boundary, tmp_path):
    mutation = boundary["mutation"]
    uri = "https://www.sec.gov/Archives/edgar/data/789019/000000000024000001/"
    primary, path = put_response(
        tmp_path,
        uri + "primary.htm",
        mutation.get("html", "<html/>").encode(),
        mutation.get("issuer_scope", CASE["issuer_id"]),
    )
    if mutation.get("remove_response"):
        path.unlink()
    elif mutation.get("corrupt_bytes"):
        path.write_bytes(b"corrupt")
    elif mutation.get("wrong_size"):
        primary["received_size"] = 500
    expected = re.escape(boundary["expected"]["outcome_code"])
    if boundary["operation"] == "source":
        failure = FileNotFoundError if mutation.get("remove_response") else ValueError
        with pytest.raises(failure, match=expected):
            reference.read_original(primary, tmp_path, False, None)
        return
    other_receipts = [
        put_response(tmp_path, uri + document, document.encode())[0]
        for document in (
            "index.json",
            "0000000000-24-000001-xbrl.zip",
            "0000000000-24-000001.txt",
        )
    ]
    filing = {
        "accession_number": "0000000000-24-000001",
        "primary_document": "primary.htm",
        "source_responses": [primary, *other_receipts],
    }
    with pytest.raises(ValueError, match=expected):
        reference.parse_filing(filing, CASE["issuer_id"], [], {}, tmp_path, False, None)


def test_exact_decimal_scale_sign_and_rounding_bounds():
    assert reference.parse_numeric("1,234.56789", "6", "-") == Decimal("-1234567890")
    assert reference.parse_numeric(
        "123456789012345678901234567890.123", "-3", "-"
    ) == Decimal("-123456789012345678901234567.890123")
    assert reference.parse_numeric("0", "6", None) == Decimal(0)
    exact = reference.decimals_interval(Decimal(105), "INF")
    rounded = reference.decimals_interval(Decimal(100), "-1")
    assert reference.intervals_overlap(
        rounded, reference.decimals_interval(Decimal(95), "INF")
    )
    assert not reference.intervals_overlap(rounded, exact)


def test_pinned_fy2023_apple_53_weeks_and_q4_missing_fx():
    quarter = reference.load_object(
        FIXTURES / "golden/quarter/aapl-historical/2023-09-30.json"
    )
    period = reference.record(quarter["period"])
    first = date.fromisoformat(str(period["fiscal_year_start"]))
    last = date.fromisoformat(str(period["end_date"]))
    assert (first.isoformat(), last.isoformat(), (last - first).days + 1) == (
        "2022-09-25",
        "2023-09-30",
        371,
    )
    fx = next(
        cell
        for cell in reference.records(quarter["cells"])
        if cell["row_id"] == "effect_of_exchange_rates_on_cash"
    )
    assert fx["value"] is None
    evidence = reference.record(fx["missing_evidence"])
    assert evidence["derived_status"] == "input_not_reported"
    scans = reference.records(evidence["primary_table_scans"])
    assert {row["accession_number"] for row in scans} == {
        "0000320193-23-000077",
        "0000320193-23-000106",
    }
    assert all(
        row["no_unmapped_primary_table_value"]
        and row["numeric_inline_facts_in_matched_rows"] == []
        for row in scans
    )


@pytest.fixture
def synthetic_basis_replay(tmp_path):
    scope = {
        "case_id": CASE["case_id"],
        "issuer_id": CASE["issuer_id"],
        "cutoff_at": "2024-11-02T00:00:00Z",
        "quarter_id": "synthetic/FY/Q4",
        "quarter_start": "2023-07-02",
        "quarter_end": "2023-09-30",
        "nine_month_end": "2023-07-01",
        "fiscal_year_start": "2022-09-25",
        "fiscal_year_days": 371,
    }
    filings, parsed, observations, source_paths, bindings = {}, {}, {}, {}, {}
    for role, form, report_end, accepted_at, fact_end, value in (
        (
            "original_annual",
            "10-K",
            "2023-09-30",
            "2023-11-02",
            "2023-09-30",
            "390000000",
        ),
        (
            "original_interim",
            "10-Q",
            "2023-07-01",
            "2023-08-03",
            "2023-07-01",
            "290000000",
        ),
        ("later_annual", "10-K", "2024-09-28", "2024-11-01", "2023-09-30", "390000000"),
        (
            "later_interim",
            "10-Q",
            "2024-06-29",
            "2024-08-01",
            "2023-07-01",
            "290000000",
        ),
    ):
        acceptance = accepted_at + "T18:00:00Z"
        note = f"Synthetic note for {role}"
        receipt, source_paths[role] = put_response(
            tmp_path,
            f"https://example.test/{role}.htm",
            f"<html><body><div>{note}</div></body></html>".encode(),
        )
        source_hash = receipt["content_hash"]
        fact = replace(
            make_fact(
                f"{role}/revenue",
                fact_end,
                value,
                start_date=scope["fiscal_year_start"],
                decimals="-6",
                accepted_at=acceptance,
                form=form,
            ),
            accession_number=role,
            primary_html_sha256=source_hash,
        )
        opening = replace(
            fact,
            observation_id=f"{role}/opening",
            row_id="cash_flow_beginning_balance",
            qname=reference.CASH_FLOW_BALANCE_QNAME,
            period={"period_type": "instant", "instant": "2022-09-24"},
            printed_row_label="Cash and restricted cash at start",
            value=Decimal("25000000"),
            raw_text="25",
        )
        for item in (fact, opening):
            observations[item.observation_id] = item.json()
            bindings[item.observation_id] = {
                "observation_id": item.observation_id,
                "sha256": reference.basis_fact_digest(item.json()),
            }
        filings[role] = {
            "accession_number": role,
            "form": form,
            "reported_period_end": report_end,
            "accepted_at": acceptance,
            "primary_document_uri": receipt["uri"],
            "primary_html_sha256": source_hash,
            "primary_html_bytes": receipt["received_size"],
            "opening_cash": bindings[opening.observation_id],
            "disclosures": {
                "policy": {
                    "xpath": "/html/body/div",
                    "sha256": hashlib.sha256(note.encode()).hexdigest(),
                }
            },
        }
        parsed[role] = reference.ParsedFiling(
            {
                **filings[role],
                "issuer_id": CASE["issuer_id"],
                "primary_receipt": receipt,
            },
            {},
            {},
            {},
            {},
            {},
        )
    pairs = [
        {
            "role": role,
            "original": bindings[f"original_{filing}/revenue"],
            "comparative": bindings[f"later_{filing}/revenue"],
        }
        for role, filing in (("annual_flow", "annual"), ("nine_month_flow", "interim"))
    ]
    proof = {
        "protocol": "issue495-reviewed-quarter-basis-v1",
        "scope": scope,
        "filings": filings,
        "rows": {"revenue": {"cash_scope": "not_applicable", "pairs": pairs}},
        "retained_submissions_sha256": "1" * 64,
        "review": {
            "verdict": "limited_support_at_filed_precision",
            "report_sha256": "2" * 64,
            "evidence_snapshot_sha256": "3" * 64,
            "independent_checker_sha256": "4" * 64,
            "accounting_scope": "consolidated_us_gaap",
            "policy_summary": "Synthetic policy",
            "cash_summary": "Synthetic cash definition",
            "limits": "Synthetic scope",
        },
    }
    cell = {
        "row_id": "revenue",
        "statement": "income_statement",
        "end_date": scope["quarter_end"],
        "value": "100000000",
        "selected_observation_ids": ["later_annual/revenue", "later_interim/revenue"],
        "basis_evidence": {"basis_conflict": None},
        "selection_decision": {
            "annual": {
                "eligible_candidate_ids": [
                    "original_annual/revenue",
                    "later_annual/revenue",
                ]
            },
            "nine_month_ytd": {
                "eligible_candidate_ids": [
                    "original_interim/revenue",
                    "later_interim/revenue",
                ]
            },
        },
    }
    golden = {
        **CASE,
        "cutoff_at": scope["cutoff_at"],
        "quarter_periods": [
            {
                "quarter_id": scope["quarter_id"],
                "start_date": scope["quarter_start"],
                "end_date": scope["quarter_end"],
                "fiscal_year_start": scope["fiscal_year_start"],
                "prior_quarter_end": scope["nine_month_end"],
                "fiscal_period_focus": "FY",
                "accession_number": "original_annual",
                "period_source": {"preceding_quarter_accession": "original_interim"},
            }
        ],
        "cells": [
            cell,
            {
                "row_id": "effect_of_exchange_rates_on_cash",
                "end_date": scope["quarter_end"],
                "value": None,
                "availability": "missing",
            },
        ],
    }
    catalog = {
        "case_id": scope["case_id"],
        "cutoff_at": scope["cutoff_at"],
        "catalog_capture": {
            "response_receipts": [
                {"content_hash": proof["retained_submissions_sha256"]}
            ]
        },
        "matching_amendment_accessions": [],
    }
    path = tmp_path / "synthetic-proof.json"
    original_proof_sha256 = hashlib.sha256(reference.json_bytes(proof)).hexdigest()

    def replay(*, preserve_reviewed_digest=False):
        payload = reference.json_bytes(proof)
        path.write_bytes(payload)
        return reference.apply_reviewed_basis_proof(
            path,
            original_proof_sha256
            if preserve_reviewed_digest
            else hashlib.sha256(payload).hexdigest(),
            golden,
            parsed,
            observations,
            catalog,
            tmp_path,
        )

    return proof, golden, observations, catalog, source_paths, replay


def test_synthetic_basis_proof_binds_selected_operands(synthetic_basis_replay):
    proof, golden, _, _, _, replay = synthetic_basis_replay
    assert replay(preserve_reviewed_digest=True) == 1
    revenue, fx = golden["cells"]
    assert revenue["value"] == "100000000"
    assert revenue["basis_evidence"]["reviewed_bridge"] == {
        "status": "limited_support_at_filed_precision",
        "proof_shard": "basis/synthetic-proof.json",
        "proof_sha256": hashlib.sha256(reference.json_bytes(proof)).hexdigest(),
        "row_id": "revenue",
        "selected_observation_ids": ["later_annual/revenue", "later_interim/revenue"],
        "public_source_available_at": "2024-11-01T18:00:00Z",
    }
    assert fx["availability"] == "missing" and "basis_evidence" not in fx


@pytest.mark.parametrize(
    ("location", "replacement", "reason"),
    [
        (("protocol",), "unknown", "protocol"),
        (("scope", "case_id"), "another_case", "case, cutoff or fiscal period"),
        (
            ("scope", "cutoff_at"),
            "2024-11-03T00:00:00Z",
            "case, cutoff or fiscal period",
        ),
        (("scope", "fiscal_year_days"), 364, "case, cutoff or fiscal period"),
        (("scope", "nine_month_end"), "2023-06-30", "case, cutoff or fiscal period"),
        (
            ("filings", "later_annual", "primary_html_sha256"),
            "9" * 64,
            "filing identity",
        ),
        (
            ("filings", "later_annual", "accepted_at"),
            "2024-11-02T00:00:01Z",
            "accepted after cutoff",
        ),
        (
            ("filings", "later_annual", "disclosures", "policy", "sha256"),
            "9" * 64,
            "disclosure differs",
        ),
        (
            ("filings", "later_annual", "disclosures", "policy", "xpath"),
            "/html/body/div[3]",
            "disclosure differs",
        ),
        (("rows",), {}, "rows differ"),
        (("rows", "revenue", "cash_scope"), "includes_restricted_cash", "cash scope"),
        (
            ("rows", "revenue", "pairs", 0, "comparative", "observation_id"),
            "later_interim/revenue",
            "selection differs",
        ),
        (
            ("rows", "revenue", "pairs", 0, "original", "sha256"),
            "9" * 64,
            "observation differs",
        ),
    ],
)
def test_synthetic_basis_proof_rejects_tampered_bindings(
    synthetic_basis_replay, location, replacement, reason
):
    proof, golden, _, _, _, replay = synthetic_basis_replay
    target = proof
    for key in location[:-1]:
        target = target[key]
    target[location[-1]] = replacement
    with pytest.raises(ValueError, match=reason):
        replay()
    assert "reviewed_bridge" not in golden["cells"][0]["basis_evidence"]


def test_synthetic_basis_proof_rejects_different_review_digest(synthetic_basis_replay):
    proof, _, _, _, _, replay = synthetic_basis_replay
    proof["review"]["report_sha256"] = "9" * 64
    with pytest.raises(ValueError, match="differs from the reviewed registry"):
        replay(preserve_reviewed_digest=True)


def test_synthetic_basis_proof_rejects_changed_source_bytes(synthetic_basis_replay):
    _, _, _, _, paths, replay = synthetic_basis_replay
    paths["later_annual"].write_bytes(
        b"<html><body><div>Edited synthetic note</div></body></html>"
    )
    with pytest.raises(ValueError, match="retained source digest differs"):
        replay()


def test_synthetic_basis_proof_rejects_changed_raw_observation_period(
    synthetic_basis_replay,
):
    _, _, observations, _, _, replay = synthetic_basis_replay
    observations["original_annual/revenue"]["period"]["start_date"] = "2022-09-26"
    with pytest.raises(ValueError, match="observation differs"):
        replay()


def test_synthetic_basis_proof_rejects_conflicting_intermediate_revision(
    synthetic_basis_replay,
):
    _, golden, observations, _, _, replay = synthetic_basis_replay
    observations["synthetic_intermediate/revenue"] = {
        **observations["original_annual/revenue"],
        "canonical_decimal": "391000000",
    }
    golden["cells"][0]["selection_decision"]["annual"]["eligible_candidate_ids"].append(
        "synthetic_intermediate/revenue"
    )
    with pytest.raises(ValueError, match="eligible observations differ"):
        replay()


def test_synthetic_basis_proof_rejects_retained_amendment(synthetic_basis_replay):
    _, _, _, catalog, _, replay = synthetic_basis_replay
    catalog["matching_amendment_accessions"].append("synthetic-amendment")
    with pytest.raises(ValueError, match="amendment scope differs"):
        replay()


def test_only_reviewed_apple_q4_rows_point_to_the_proof():
    manifest = reference.load_object(FIXTURES / "issue495-golden-manifest.json")
    proof_path = "basis/aapl-historical-2023-09-30.json"
    payload = (FIXTURES / proof_path).read_bytes()
    proof = reference.ReviewedBasisProof.model_validate_json(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert manifest["inputs"][proof_path] == digest
    assert len(proof.rows) == 24
    assert sum(len(row.pairs) for row in proof.rows.values()) == 35
    linked_rows = set()
    for path in (FIXTURES / "golden/quarter").glob("*/*.json"):
        for cell in reference.load_object(path).get("cells", []):
            link = cell.get("basis_evidence", {}).get("reviewed_bridge")
            if link is None:
                continue
            assert path.parent.name == "aapl-historical" and path.stem == "2023-09-30"
            assert link["proof_shard"] == proof_path and link["proof_sha256"] == digest
            assert link["row_id"] == cell["row_id"]
            assert link["selected_observation_ids"] == cell["selected_observation_ids"]
            assert link["public_source_available_at"] == "2024-11-01T10:01:36.000Z"
            linked_rows.add(cell["row_id"])
    assert linked_rows == set(proof.rows)
    assert "effect_of_exchange_rates_on_cash" not in linked_rows


def test_cohort_basis_and_availability_covers_every_published_cell():
    manifest = reference.load_object(FIXTURES / "issue495-golden-manifest.json")
    observations = {
        identity: fact
        for path in (FIXTURES / "golden/sources").glob("*.json")
        for identity, fact in reference.load_object(path)["observations"].items()
    }
    reached_late_prior = set()
    counts = {}
    for frequency in ("quarter", "ttm"):
        counts[frequency] = {"supported_limited": 0, "not_comparable_missing_source": 0}
    for case_path in (FIXTURES / "cases").glob("*.json"):
        case_id = case_path.stem
        name = f"basis/cohort-{case_id}.json"
        proof = reference.load_object(FIXTURES / name)
        assert (
            manifest["inputs"][name]
            == hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        )
        quarter_times = {}
        for frequency, periods in (
            ("quarter", proof["quarters"]),
            ("ttm", proof["ttm"]),
        ):
            for end, period in periods.items():
                path = FIXTURES / "golden" / frequency / case_id / f"{end}.json"
                cells = reference.load_object(path)["cells"]
                assert {cell["row_id"] for cell in cells} == period["rows"].keys()
                for cell in cells:
                    row = period["rows"][cell["row_id"]]
                    link = cell["reviewed_cohort_basis"]
                    assert link["case_proof_shard"] == name
                    assert link["case_proof_sha256"] == manifest["inputs"][name]
                    assert (
                        link["filing_proof_sha256"]
                        == manifest["inputs"][link["filing_proof_shard"]]
                    )
                    assert (
                        link["review_matrix_sha256"]
                        == "a9b4fc174b3ca1350d1f2a363ee5993580a07255332c4f004ec552c3008c664b"
                    )
                    assert link["cell_id"] == cell["cell_id"]
                    assert link["status"] == row["verdict"]
                    counts[frequency][link["status"]] += 1
                    assert (
                        link["uses_source_admission_blocked_accession"]
                        == row["uses_blocked_source"]
                    )
                    if frequency == "quarter":
                        selected = cell["selected_observation_ids"]
                        difference = [
                            cell[key]["observation_id"]
                            for key in (
                                "annual_input",
                                "nine_month_ytd_input",
                                "current_ytd_input",
                                "prior_ytd_input",
                            )
                            if cell.get(key)
                        ]
                        assert selected == row["selected_observation_ids"]
                        assert difference == row["difference_observation_ids"]
                        times = [
                            observations[key]["accepted_at"]
                            for key in set(selected + difference)
                        ]
                        if (
                            cell["availability"] == "reported_with_derived_crosscheck"
                            and datetime.fromisoformat(
                                observations[selected[0]]["accepted_at"]
                            )
                            < max(map(datetime.fromisoformat, times))
                        ):
                            reached_late_prior.add(cell["cell_id"])
                        quarter_times[cell["cell_id"]] = cell["source_available_at"]
                    else:
                        assert (
                            cell["basis_check"]["comparability_status"]
                            == link["status"]
                        )
                        assert (
                            cell["selected_input_cell_ids"]
                            == row["selected_quarter_cell_ids"]
                        )
                        times = [
                            quarter_times[key]
                            for key in cell["required_input_cell_ids"]
                            if quarter_times[key] is not None
                        ]
                    assert cell["source_available_at"] == max(
                        times, key=datetime.fromisoformat, default=None
                    )
                    assert cell["source_available_at"] == row["source_available_at"]
    assert counts == {
        "quarter": {"supported_limited": 784, "not_comparable_missing_source": 16},
        "ttm": {"supported_limited": 490, "not_comparable_missing_source": 10},
    }
    assert len(reached_late_prior) == 24
    assert {"/".join(key.split("/")[:2]) for key in reached_late_prior} == {
        "msft-historical/2023-12-31",
        "msft-current/2025-12-31",
    }


@pytest.fixture
def synthetic_cohort_replay(monkeypatch):
    case_id = "synthetic"
    end = "2023-12-31"
    earliest = "2024-01-01T18:00:00Z"
    direct_at = "2024-02-01T18:00:00Z"
    crosscheck_at = "2024-07-31T18:00:00Z"
    original = replace(
        make_fact(
            "original/q1",
            "2023-09-30",
            "100000000",
            accepted_at=earliest,
            decimals="-6",
        ),
        accession_number="original",
    )
    comparative = replace(
        original,
        observation_id="comparative/q1",
        accession_number="comparative",
        accepted_at=crosscheck_at,
    )
    direct = make_fact(
        "synthetic/q2",
        end,
        "110000000",
        start_date="2023-10-01",
        accepted_at=direct_at,
        decimals="-6",
    )
    ytd = make_fact(
        "synthetic/ytd", end, "210000000", accepted_at=direct_at, decimals="-6"
    )
    future = replace(
        original,
        observation_id="late/q1",
        accession_number="late",
        accepted_at="2024-08-01T00:00:01Z",
        value=Decimal("990000000"),
    )
    observations = {
        fact.observation_id: fact.json()
        for fact in (original, comparative, direct, ytd, future)
    }
    period = {
        "quarter_id": "synthetic:Q2:2023-12-31",
        "accession_number": "synthetic",
        "fiscal_year_focus": "2024",
        "fiscal_period_focus": "Q2",
        "fiscal_year_start": "2023-07-01",
        "start_date": "2023-10-01",
        "end_date": end,
        "inclusive_calendar_days": 92,
        "period_source": {"kind": "synthetic"},
    }
    cell = {
        "cell_id": f"{case_id}/{end}/revenue",
        "row_id": "revenue",
        "statement": "income_statement",
        "end_date": end,
        "availability": "reported_with_derived_crosscheck",
        "value": "110000000",
        "selected_observation_ids": [direct.observation_id],
        "current_ytd_input": {"observation_id": ytd.observation_id},
        "prior_ytd_input": {"observation_id": comparative.observation_id},
        "source_available_at": crosscheck_at,
    }
    row = {
        "verdict": "supported_limited",
        "cell_id": cell["cell_id"],
        "statement": cell["statement"],
        "selected_observation_ids": [direct.observation_id],
        "difference_observation_ids": [ytd.observation_id, comparative.observation_id],
        "original_comparative_pairs": [
            [original.observation_id, comparative.observation_id]
        ],
        "same_filing_duplicate_pairs": [],
        "source_available_at": crosscheck_at,
        "uses_blocked_source": False,
    }
    proof = {
        "protocol": "issue495-reviewed-cohort-basis-v1",
        "authority": {
            "matrix_sha256": "1" * 64,
            "index_sha256": "2" * 64,
            "scope": "25 selected primary statement rows at filed USD million precision, exact fixed cohort only",
        },
        **CASE,
        "catalog": {
            "submissions_sha256": "3" * 64,
            "report_dates": ["2023-09-30", end],
            "recent_accepted_range": ["2020-01-01T00:00:00Z", "2024-08-02T00:00:00Z"],
            "archived_filing_date_upper_bounds": ["2019-09-30"],
        },
        "source_accessions": ["original", "comparative", "synthetic"],
        "observation_sha256": {
            key: reference.cohort_fact_digest(fact)
            for key, fact in observations.items()
            if key != future.observation_id
        },
        "quarters": {
            end: {
                "period": period,
                "rows": {"revenue": row},
                "fiscal_opening_cash": [],
                "original_anchor_accessions": [],
            }
        },
        "ttm": {},
    }
    golden = {"quarter_periods": [period], "cells": [cell]}
    path = "basis/synthetic-cohort-proof.json"
    monkeypatch.setitem(reference.COHORT_BASIS_SHARDS, path, "4" * 64)

    def replay():
        reference.replay_cohort_quarters(
            reference.CohortCaseProof.model_validate(proof),
            golden,
            observations,
            {},
            path,
        )
        return golden["cells"][0]["reviewed_cohort_basis"]

    return proof, row, observations, replay


def test_synthetic_cohort_excludes_late_candidate_and_preserves_review(
    synthetic_cohort_replay,
):
    proof, _, observations, replay = synthetic_cohort_replay
    proof["source_accessions"].append("late")
    assert replay()["status"] == "supported_limited"
    observations["late/q1"]["canonical_decimal"] = "1900000000"
    assert replay()["status"] == "supported_limited"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("issuer_id", "0000000001", "fact differs"),
        ("entity_identifier", "0000000001", "fact differs"),
        ("unit_measures", ["iso4217:EUR"], "fact differs"),
        (
            "dimensions",
            [{"dimension": "segment", "member": "synthetic"}],
            "fact differs",
        ),
        (
            "period",
            {
                "period_type": "duration",
                "start_date": "2023-07-02",
                "end_date": "2023-09-30",
            },
            "comparative set differs",
        ),
        ("cash_basis", "different_basis", "comparative set differs"),
        ("revision_basis_id", "different_revision", "fact differs"),
        ("canonical_decimal", "199000000", "revision differs"),
        ("accepted_at", "2024-08-02T00:00:00Z", "fact differs"),
    ],
)
def test_synthetic_cohort_rejects_noncomparable_source(
    synthetic_cohort_replay, field, value, error
):
    proof, _, observations, replay = synthetic_cohort_replay
    changed = observations["original/q1"]
    changed[field] = value
    proof["observation_sha256"]["original/q1"] = reference.cohort_fact_digest(changed)
    with pytest.raises(ValueError, match=error):
        replay()


def test_synthetic_cohort_rejects_same_filing_conflict_and_duplicate_proof(
    synthetic_cohort_replay,
):
    _, row, observations, replay = synthetic_cohort_replay
    row["original_comparative_pairs"].append(row["original_comparative_pairs"][0])
    with pytest.raises(ValueError, match="comparative set differs"):
        replay()
    row["original_comparative_pairs"].pop()
    observations["comparative/duplicate"] = {
        **observations["comparative/q1"],
        "observation_id": "comparative/duplicate",
        "canonical_decimal": "199000000",
    }
    with pytest.raises(ValueError, match="revision differs"):
        replay()


def test_synthetic_cohort_shard_rejects_tampering_and_duplicate_keys(
    tmp_path, synthetic_cohort_replay
):
    proof, _, _, _ = synthetic_cohort_replay
    path = tmp_path / "synthetic-cohort.json"
    original = reference.json_bytes(proof)
    pinned = hashlib.sha256(original).hexdigest()
    path.write_bytes(original)
    assert (
        reference.pinned_basis_shard(path, pinned, reference.CohortCaseProof).case_id
        == "synthetic"
    )
    tampered = original.replace(b'"case_id":"synthetic"', b'"case_id":"tampered"')
    path.write_bytes(tampered)
    with pytest.raises(ValueError, match="digest differs"):
        reference.pinned_basis_shard(path, pinned, reference.CohortCaseProof)
    duplicate = original.replace(
        b'"case_id":"synthetic"', b'"case_id":"tampered","case_id":"synthetic"'
    )
    path.write_bytes(duplicate)
    with pytest.raises(ValueError, match="duplicate field"):
        reference.pinned_basis_shard(
            path, hashlib.sha256(duplicate).hexdigest(), reference.CohortCaseProof
        )


def test_synthetic_cohort_replays_raw_disclosure_and_rejects_wrong_locator(tmp_path):
    uri = "https://example.test/synthetic.htm"
    note = "Synthetic basis disclosure"
    receipt, retained = put_response(
        tmp_path, uri, f"<html><body><p>{note}</p></body></html>".encode()
    )
    disclosure = {
        "sha256": hashlib.sha256(note.encode()).hexdigest(),
        "xpath": "/html/body/p",
    }
    source = {
        "issuer_id": CASE["issuer_id"],
        "form": "10-K",
        "reported_period_end": "2024-06-30",
        "accepted_at": "2024-07-31T12:00:00Z",
        "primary_html_sha256": receipt["content_hash"],
    }
    filing = {
        **source,
        "primary_document_uri": uri,
        "primary_html_bytes": receipt["received_size"],
        "source_roles_by_case": {"synthetic": "target_quarter_source"},
        "disclosures": {"consolidated_gaap": [disclosure]},
    }
    parsed = reference.ParsedFiling(
        {**source, "accession_number": "synthetic", "primary_receipt": receipt},
        {},
        {},
        {},
        {},
        {},
    )

    def replay():
        return reference.replay_cohort_filing(
            "synthetic",
            reference.CohortFilingBasis.model_validate(filing),
            parsed,
            tmp_path,
        )

    assert replay() == {}
    disclosure["xpath"] = "/html/body/p[2]"
    with pytest.raises(ValueError, match="accounting disclosure differs"):
        replay()
    disclosure["xpath"] = "/html/body/p"
    retained.write_bytes(f"<html><body><p>{note[:-1]}X</p></body></html>".encode())
    with pytest.raises(ValueError, match="retained source digest differs"):
        replay()


@pytest.mark.parametrize(
    "amendment_field", ["matching_amendment_accessions", "undated_amendment_accessions"]
)
def test_synthetic_cohort_rejects_catalog_amendments(
    synthetic_cohort_replay, amendment_field
):
    proof, _, _, _ = synthetic_cohort_replay
    filings = {
        accession: {
            "issuer_id": CASE["issuer_id"],
            "form": "10-Q",
            "reported_period_end": "2023-12-31",
            "accepted_at": "2024-07-31T12:00:00Z",
            "primary_document_uri": "https://example.test/synthetic.htm",
            "primary_html_sha256": "4" * 64,
            "primary_html_bytes": 1,
            "source_roles_by_case": {"synthetic": "target_quarter_source"},
            "disclosures": {},
        }
        for accession in proof["source_accessions"]
    }
    registry = reference.CohortFilingRegistry.model_validate(
        {
            "protocol": "issue495-reviewed-filing-basis-v1",
            "authority": proof["authority"],
            "filings": filings,
        }
    )
    case = {
        **CASE,
        "filings": [
            {"accession_number": accession, "source_role": "target_quarter_source"}
            for accession in proof["source_accessions"]
        ],
    }
    catalog = {
        "case_id": CASE["case_id"],
        "cutoff_at": CASE["cutoff_at"],
        "catalog_capture": {
            "response_receipts": [
                {"content_hash": proof["catalog"]["submissions_sha256"]}
            ]
        },
        "rows": [
            {"accessionNumber": accession} for accession in proof["source_accessions"]
        ],
        "report_date_range": proof["catalog"]["report_dates"],
        "recent_accepted_range": proof["catalog"]["recent_accepted_range"],
        "older_submissions_files_outside_filing_date_range": [
            {"filingTo": "2019-09-30"}
        ],
        "matching_amendment_accessions": [],
        "undated_amendment_accessions": [],
    }
    resolved = reference.CohortCaseProof.model_validate(proof)
    reference.replay_cohort_catalog(resolved, case, catalog, registry)
    catalog[amendment_field].append("synthetic-amendment")
    with pytest.raises(ValueError, match="amendment scope differs"):
        reference.replay_cohort_catalog(resolved, case, catalog, registry)
