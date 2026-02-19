from src.shared.kernel.tools.logger import get_logger, log_event

from ..valuation_bank.schemas import BankParams
from ..valuation_ev_ebitda.schemas import EVEbitdaParams
from ..valuation_ev_revenue.schemas import EVRevenueParams
from ..valuation_eva.schemas import EvaParams
from ..valuation_reit_ffo.schemas import ReitFfoParams
from ..valuation_residual_income.schemas import ResidualIncomeParams
from ..valuation_saas.schemas import SaaSParams

logger = get_logger(__name__)


class AuditResult:
    def __init__(self, passed: bool, messages: list[str]):
        self.passed = passed
        self.messages = messages


def _finalize_audit(model_type: str, messages: list[str]) -> AuditResult:
    fail_count = len([m for m in messages if m.startswith("FAIL:")])
    warn_count = len([m for m in messages if m.startswith("WARN:")])
    passed = fail_count == 0
    log_event(
        logger,
        event="valuation_audit_completed",
        message="valuation audit completed",
        fields={
            "model_type": model_type,
            "passed": passed,
            "fail_count": fail_count,
            "warn_count": warn_count,
        },
    )
    return AuditResult(passed, messages)


def audit_saas_params(params: SaaSParams) -> AuditResult:
    messages = []

    # Rule 1: Terminal Growth
    if params.terminal_growth > 0.04:
        messages.append(
            f"FAIL: Terminal growth {params.terminal_growth} exceeds 4% GDP cap."
        )

    # Rule 2: WACC
    if params.wacc < 0.05:
        messages.append(f"FAIL: WACC {params.wacc} is unrealistically low (< 5%).")

    # Rule 3: SBC Check
    if all(s == 0 for s in params.sbc_rates):
        messages.append("WARN: SBC rates are all 0%. This is unusual for SaaS.")

    return _finalize_audit("saas", messages)


def audit_bank_params(params: BankParams) -> AuditResult:
    messages = []

    if params.terminal_growth > 0.04:
        messages.append(
            f"FAIL: Terminal growth {params.terminal_growth} exceeds 4% GDP cap."
        )

    if params.cost_of_equity < 0.06:
        messages.append(f"FAIL: Cost of Equity {params.cost_of_equity} is too low.")

    return _finalize_audit("bank", messages)


def audit_ev_revenue_params(params: EVRevenueParams) -> AuditResult:
    messages = []

    if params.revenue <= 0:
        messages.append("FAIL: Revenue must be positive.")
    if params.ev_revenue_multiple <= 0:
        messages.append("FAIL: EV/Revenue multiple must be positive.")
    if params.shares_outstanding <= 0:
        messages.append("FAIL: Shares outstanding must be positive.")

    return _finalize_audit("ev_revenue", messages)


def audit_ev_ebitda_params(params: EVEbitdaParams) -> AuditResult:
    messages = []

    if params.ebitda <= 0:
        messages.append("FAIL: EBITDA must be positive.")
    if params.ev_ebitda_multiple <= 0:
        messages.append("FAIL: EV/EBITDA multiple must be positive.")
    if params.shares_outstanding <= 0:
        messages.append("FAIL: Shares outstanding must be positive.")

    return _finalize_audit("ev_ebitda", messages)


def audit_reit_ffo_params(params: ReitFfoParams) -> AuditResult:
    messages = []

    if params.ffo <= 0:
        messages.append("FAIL: FFO must be positive.")
    if params.ffo_multiple <= 0:
        messages.append("FAIL: FFO multiple must be positive.")
    if params.shares_outstanding <= 0:
        messages.append("FAIL: Shares outstanding must be positive.")

    return _finalize_audit("reit_ffo", messages)


def audit_residual_income_params(params: ResidualIncomeParams) -> AuditResult:
    messages = []

    if params.current_book_value <= 0:
        messages.append("FAIL: Current book value must be positive.")
    if not params.projected_residual_incomes:
        messages.append("FAIL: Projected residual incomes cannot be empty.")
    if params.required_return <= 0:
        messages.append("FAIL: Required return must be positive.")
    if params.terminal_growth >= params.required_return:
        messages.append("FAIL: Terminal growth must be less than required return.")
    if params.shares_outstanding <= 0:
        messages.append("FAIL: Shares outstanding must be positive.")

    return _finalize_audit("residual_income", messages)


def audit_eva_params(params: EvaParams) -> AuditResult:
    messages = []

    if params.current_invested_capital <= 0:
        messages.append("FAIL: Invested capital must be positive.")
    if not params.projected_evas:
        messages.append("FAIL: Projected EVA values cannot be empty.")
    if params.wacc <= 0:
        messages.append("FAIL: WACC must be positive.")
    if params.terminal_growth >= params.wacc:
        messages.append("FAIL: Terminal growth must be less than WACC.")
    if params.shares_outstanding <= 0:
        messages.append("FAIL: Shares outstanding must be positive.")

    return _finalize_audit("eva", messages)
