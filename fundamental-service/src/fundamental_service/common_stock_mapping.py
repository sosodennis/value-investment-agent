"""Standard common-equity component counts; no stock-class rights inference."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from .accounting_roles import (
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleError,
    AccountingRoleRules,
    AccountingRoleRuleSetV1,
    IssuerAccountingRoleRuleSetV1,
    evaluate_period_rule,
)
from .arelle_parser import ParsedXbrlFactV1, fact_semantic_digest
from .facts import select_fact
from .original_issuer import OriginalIssuerEvidenceV1
from .sec_rebuild import parsed_facts_to_candidates
from .serialization import sha256_digest
from .snapshots import SnapshotError

COMMON_STOCK = "classified:CommonStockEquityComponent"
_CONCEPT = "us-gaap:CommonStockSharesOutstanding"
_DIMENSIONS = (("us-gaap:StatementEquityComponentsAxis", "us-gaap:CommonStockMember"),)
_NAMESPACES = frozenset(f"http://fasb.org/us-gaap/{year}" for year in range(2023, 2027))
_POLICY = "standard-common-equity-component-shares-v1"


def common_stock_component_present(original: OriginalIssuerEvidenceV1) -> bool:
    return any(
        f.concept == _CONCEPT and f.dimensions == _DIMENSIONS
        for f in original.report.facts
    )


@dataclass(frozen=True)
class CommonStockSelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    reason_codes: tuple[str, ...] = ()


def _eligible(fact: ParsedXbrlFactV1, cik: str) -> bool:
    try:
        value = Decimal(fact.value)
    except InvalidOperation:
        return False
    return (
        fact.is_numeric
        and value.is_finite()
        and value >= 0
        and fact.namespace_uri in _NAMESPACES
        and fact.unit == "xbrli:shares"
        and fact.dimensions in ((), _DIMENSIONS)
        and fact.consolidation_scope
        == ("segmented" if fact.dimensions else "consolidated")
        and fact.security_scope
        in ({"segmented"} if fact.dimensions else {"issuer", "unspecified"})
        and fact.entity_scheme == "http://www.sec.gov/CIK"
        and re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "") is not None
        and int(fact.entity_identifier or "0") == int(cik)
        and fact.instant is not None
        and fact.period_start is None
        and fact.period_end is None
        and re.fullmatch(r"-?[0-9]+", fact.decimals or "") is not None
    )


def select_common_stock(
    original: OriginalIssuerEvidenceV1, *, security_id: str | None = None
) -> CommonStockSelection:
    facts = tuple(
        sorted(
            (
                f
                for f in original.report.facts
                if f.concept == _CONCEPT and f.dimensions in ((), _DIMENSIONS)
            ),
            key=sha256_digest,
        )
    )
    if not facts or any(not _eligible(f, original.source.cik) for f in facts):
        return CommonStockSelection(
            reason_codes=("MAPPING_COMMON_STOCK_COMPONENT_INVALID",)
        )
    selected: list[ParsedXbrlFactV1] = []
    periods: list[AccountingPeriodRuleV1] = []
    for instant in sorted({f.instant for f in facts if f.instant is not None}):
        if original.report_period_end is None or instant > original.report_period_end:
            return CommonStockSelection(reason_codes=("MAPPING_PERIOD_AFTER_ORIGINAL",))
        matches = tuple(f for f in facts if f.instant == instant)
        if len({f.namespace_uri for f in matches}) != 1:
            return CommonStockSelection(
                reason_codes=("MAPPING_COMMON_STOCK_COMPONENT_INVALID",)
            )
        try:
            candidates = parsed_facts_to_candidates(
                original.report.model_copy(update={"facts": matches}),
                source=original.source,
                issuer_id=original.source.cik,
                normalized_field="common_shares_outstanding",
            )
            selection = select_fact(candidates, original.decision_at)
        except SnapshotError as error:
            return CommonStockSelection(reason_codes=(error.code,))
        if selection.fact is None:
            return CommonStockSelection(
                reason_codes=tuple(sorted({issue.code for issue in selection.issues}))
            )
        chosen = next(
            f
            for f in matches
            if Decimal(f.value) == selection.fact.value
            and int(f.decimals or "0") == selection.fact.decimals
        )
        selected.append(chosen)
        periods.append(
            AccountingPeriodRuleV1(
                period=AccountingPeriodV1(period_end=instant, instant=True),
                disposition="classified",
                components=(
                    AccountingComponentV1(
                        parsed_fact_digest=sha256_digest(chosen),
                        equity_component="common_stock",
                    ),
                ),
                rationale=_POLICY,
            )
        )
    rules: AccountingRoleRules = IssuerAccountingRoleRuleSetV1(
        policy_version=_POLICY,
        normalized_field="common_shares_outstanding",
        issuer_id=original.source.cik,
        accession_number=original.source.accession_number,
        raw_content_hash=original.source.content_hash,
        parser_input_hash=original.source.parser_input_hash,
        parser_fact_digest=fact_semantic_digest(original.report),
        unit="xbrli:shares",
        currency=None,
        periods=tuple(periods),
    )
    for period, fact in zip(periods, selected):
        try:
            evaluate_period_rule(rules, period, (fact,))
        except AccountingRoleError as error:
            return CommonStockSelection(reason_codes=(error.code,))
    if security_id is not None:
        rules = AccountingRoleRuleSetV1.model_validate(
            {
                **rules.model_dump(exclude={"protocol", "security_id"}),
                "security_id": security_id,
            }
        )
    return CommonStockSelection(rules=rules, selected=tuple(selected))
