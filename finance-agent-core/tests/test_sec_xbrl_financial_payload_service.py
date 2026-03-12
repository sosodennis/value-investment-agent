from __future__ import annotations

from src.agents.fundamental.domain.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)
from src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.cache.filing_cache_service import (
    FilingCacheService,
)
from src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service import (
    fetch_financial_data,
    fetch_financial_reports_payload,
    reset_filing_cache_service_for_tests,
    set_filing_cache_service_for_tests,
)
from src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.report_contracts import (
    BaseFinancialModel,
    FinancialReport,
)


def _report(
    year: int,
    *,
    selection_mode: str,
    arelle_validation_issues: list[dict[str, object]] | None = None,
    extra_filing_metadata: dict[str, object] | None = None,
) -> FinancialReport:
    filing_metadata: dict[str, object] = {
        "form": "10-K",
        "matched_fiscal_year": year,
        "selection_mode": selection_mode,
    }
    if arelle_validation_issues is not None:
        filing_metadata["arelle_validation_issues"] = arelle_validation_issues
    if isinstance(extra_filing_metadata, dict):
        filing_metadata.update(extra_filing_metadata)

    return FinancialReport(
        base=BaseFinancialModel(
            fiscal_year=TraceableField(
                name="Fiscal Year",
                value=str(year),
                provenance=ManualProvenance(description="test"),
            )
        ),
        industry_type="Industrial",
        extension_type="Industrial",
        filing_metadata=filing_metadata,
    )


def test_fetch_financial_data_prioritizes_latest_filing_then_descending_history(
    monkeypatch,
) -> None:
    latest = _report(2025, selection_mode="latest_available")
    by_year = {
        2024: _report(2024, selection_mode="fiscal_year_match"),
        2023: _report(2023, selection_mode="fiscal_year_match"),
    }
    requested_years: list[int] = []

    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.FinancialReportFactory.create_latest_report",
        staticmethod(lambda _ticker: latest),
    )

    def _create_report(_ticker: str, fiscal_year: int | None) -> FinancialReport:
        if fiscal_year is None:
            raise AssertionError("year-based create_report should not receive None")
        requested_years.append(fiscal_year)
        report = by_year.get(fiscal_year)
        if report is None:
            raise ValueError("not found")
        return report

    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.FinancialReportFactory.create_report",
        staticmethod(_create_report),
    )

    reports = fetch_financial_data("NVDA", years=3)

    years = [int(float(report.base.fiscal_year.value)) for report in reports]
    assert years == [2025, 2024, 2023]
    assert requested_years[:2] == [2024, 2023]
    assert reports[0].filing_metadata is not None
    assert reports[0].filing_metadata.get("selection_mode") == "latest_available"


def test_fetch_financial_data_uses_five_year_default_window(monkeypatch) -> None:
    latest = _report(2025, selection_mode="latest_available")
    by_year = {
        2024: _report(2024, selection_mode="fiscal_year_match"),
        2023: _report(2023, selection_mode="fiscal_year_match"),
        2022: _report(2022, selection_mode="fiscal_year_match"),
        2021: _report(2021, selection_mode="fiscal_year_match"),
    }
    requested_years: list[int] = []

    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.FinancialReportFactory.create_latest_report",
        staticmethod(lambda _ticker: latest),
    )

    def _create_report(_ticker: str, fiscal_year: int | None) -> FinancialReport:
        if fiscal_year is None:
            raise AssertionError("year-based create_report should not receive None")
        requested_years.append(fiscal_year)
        report = by_year.get(fiscal_year)
        if report is None:
            raise ValueError("not found")
        return report

    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.FinancialReportFactory.create_report",
        staticmethod(_create_report),
    )

    reports = fetch_financial_data("NVDA")

    years = [int(float(report.base.fiscal_year.value)) for report in reports]
    assert years == [2025, 2024, 2023, 2022, 2021]
    assert requested_years[:4] == [2024, 2023, 2022, 2021]


def test_fetch_financial_reports_payload_uses_cache_on_warm_path(
    monkeypatch,
    tmp_path,
) -> None:
    cache_service = FilingCacheService(
        l1_ttl_seconds=3600,
        l2_enabled=False,
        l3_enabled=True,
        l3_cache_dir=str(tmp_path / "sec_xbrl_cache"),
    )
    set_filing_cache_service_for_tests(cache_service)
    fetch_call_count = {"value": 0}

    def _fetch(_ticker: str, years: int = 5) -> list[FinancialReport]:
        fetch_call_count["value"] += 1
        if fetch_call_count["value"] > 1:
            raise AssertionError("warm cache should bypass fetch_financial_data")
        return [_report(2025, selection_mode=f"latest_available_{years}")]

    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.fetch_financial_data",
        _fetch,
    )

    try:
        cold_payload = fetch_financial_reports_payload("AMZN", years=3)
        warm_payload = fetch_financial_reports_payload("AMZN", years=3)
    finally:
        reset_filing_cache_service_for_tests()

    assert fetch_call_count["value"] == 1
    assert isinstance(cold_payload.get("diagnostics"), dict)
    warm_diagnostics = warm_payload.get("diagnostics")
    assert isinstance(warm_diagnostics, dict)
    cache_diagnostics = warm_diagnostics.get("cache")
    assert isinstance(cache_diagnostics, dict)
    assert cache_diagnostics.get("cache_hit") is True
    assert cache_diagnostics.get("cache_layer") == "L1"
    assert isinstance(warm_payload.get("financial_reports"), list)


def test_fetch_financial_reports_payload_emits_quality_gate_payload(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.fetch_financial_data",
        lambda _ticker, years=5: [
            _report(2025, selection_mode=f"latest_available_{years}")
        ],
    )

    payload = fetch_financial_reports_payload("AMZN", years=3)
    quality_gates = payload.get("quality_gates")
    assert isinstance(quality_gates, dict)
    assert quality_gates.get("status") in {"pass", "warn", "block"}
    assert isinstance(quality_gates.get("issues"), list)


def test_fetch_financial_reports_payload_projects_arelle_validation_issues_into_diagnostics(
    monkeypatch,
    tmp_path,
) -> None:
    cache_service = FilingCacheService(
        l1_ttl_seconds=3600,
        l2_enabled=False,
        l3_enabled=True,
        l3_cache_dir=str(tmp_path / "sec_xbrl_cache_issues"),
    )
    set_filing_cache_service_for_tests(cache_service)

    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.fetch_financial_data",
        lambda _ticker, years=5: [
            _report(
                2025,
                selection_mode=f"latest_available_{years}",
                arelle_validation_issues=[
                    {
                        "code": "EFM.6.05.20",
                        "source": "EFM",
                        "severity": "error",
                        "message": "invalid context",
                        "field_key": "income_before_tax",
                    }
                ],
            )
        ],
    )

    try:
        payload = fetch_financial_reports_payload("AMZN", years=3)
    finally:
        reset_filing_cache_service_for_tests()

    diagnostics = payload.get("diagnostics")
    assert isinstance(diagnostics, dict)
    issues = diagnostics.get("dqc_efm_issues")
    assert isinstance(issues, list)
    assert issues
    first_issue = issues[0]
    assert isinstance(first_issue, dict)
    assert first_issue.get("code") == "EFM.6.05.20"
    assert first_issue.get("source") == "EFM"
    assert first_issue.get("blocking") is True

    quality_gates = payload.get("quality_gates")
    assert isinstance(quality_gates, dict)
    assert quality_gates.get("status") == "block"


def test_fetch_financial_reports_payload_emits_arelle_runtime_diagnostics(
    monkeypatch,
    tmp_path,
) -> None:
    cache_service = FilingCacheService(
        l1_ttl_seconds=3600,
        l2_enabled=False,
        l3_enabled=True,
        l3_cache_dir=str(tmp_path / "sec_xbrl_cache_runtime_diag"),
    )
    set_filing_cache_service_for_tests(cache_service)
    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.fetch_financial_data",
        lambda _ticker, years=5: [
            _report(
                2025,
                selection_mode=f"latest_available_{years}",
                extra_filing_metadata={
                    "arelle_parse_latency_ms": 120.5,
                    "arelle_runtime_lock_wait_ms": 3.2,
                    "arelle_runtime_isolation_mode": "serial",
                    "arelle_validation_mode": "efm_validate",
                },
            )
        ],
    )

    try:
        payload = fetch_financial_reports_payload("AMZN", years=3)
    finally:
        reset_filing_cache_service_for_tests()

    diagnostics = payload.get("diagnostics")
    assert isinstance(diagnostics, dict)
    arelle_runtime = diagnostics.get("arelle_runtime")
    assert isinstance(arelle_runtime, dict)
    assert arelle_runtime.get("report_count") == 1
    assert arelle_runtime.get("parse_latency_ms_avg") == 120.5
    assert arelle_runtime.get("runtime_lock_wait_ms_avg") == 3.2
    assert arelle_runtime.get("isolation_modes") == ["serial"]
    assert arelle_runtime.get("validation_modes") == ["efm_validate"]


def test_fetch_financial_reports_payload_cache_key_includes_validation_profile(
    monkeypatch, tmp_path
) -> None:
    cache_service = FilingCacheService(
        l1_ttl_seconds=3600,
        l2_enabled=False,
        l3_enabled=True,
        l3_cache_dir=str(tmp_path / "sec_xbrl_cache_taxonomy_key"),
    )
    set_filing_cache_service_for_tests(cache_service)
    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl.extract.financial_payload_service.fetch_financial_data",
        lambda _ticker, years=5: [
            _report(
                2025,
                selection_mode=f"latest_available_{years}",
                extra_filing_metadata={
                    "cik": "0001018724",
                    "accession_number": "0001018724-26-000012",
                    "taxonomy_version": "us-gaap-2025",
                    "arelle_validation_mode": "efm_dqc_validate",
                    "arelle_disclosure_system": "efm",
                    "arelle_plugins": ["validate/EFM", "validate/DQC"],
                    "arelle_packages": ["sec-taxonomy-2025.zip"],
                    "arelle_version": "2.37.77",
                },
            )
        ],
    )

    try:
        payload = fetch_financial_reports_payload("AMZN", years=3)
    finally:
        reset_filing_cache_service_for_tests()

    diagnostics = payload.get("diagnostics")
    assert isinstance(diagnostics, dict)
    cache_diagnostics = diagnostics.get("cache")
    assert isinstance(cache_diagnostics, dict)
    payload_cache_key = cache_diagnostics.get("payload_cache_key")
    assert isinstance(payload_cache_key, str)
    assert "us-gaap-2025__efm_dqc_validate__efm__2.37.77__" in payload_cache_key
