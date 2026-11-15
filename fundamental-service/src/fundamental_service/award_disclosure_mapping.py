"""Source-bound selection of aggregate award-type disclosures."""

from dataclasses import dataclass
from decimal import Decimal

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

from .award_disclosures import (
    AWARD_DISCLOSURE_DIMENSIONS,
    AWARD_DISCLOSURE_POLICY,
    AWARD_DISCLOSURE_ROLES,
    AWARD_DISCLOSURE_SCOPE,
    matches_award_disclosure,
)


@dataclass(frozen=True)
class AwardDisclosureSelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_award_disclosure(
    original: OriginalIssuerEvidenceV1, role: str, *, security_id: str | None = None
) -> AwardDisclosureSelection:
    definition = AWARD_DISCLOSURE_ROLES[role]
    facts = tuple(
        sorted(
            (
                f
                for f in original.report.facts
                if f.concept == definition.concept
                and f.dimensions == AWARD_DISCLOSURE_DIMENSIONS
            ),
            key=sha256_digest,
        )
    )
    if not facts:
        return AwardDisclosureSelection(
            reason_codes=("MAPPING_AWARD_DISCLOSURE_MISSING",)
        )
    if any(
        not matches_award_disclosure(f, role=role, issuer_id=original.source.cik)
        for f in facts
    ):
        return AwardDisclosureSelection(
            reason_codes=("MAPPING_AWARD_DISCLOSURE_INVALID",)
        )
    selected: list[ParsedXbrlFactV1] = []
    periods: list[AccountingPeriodRuleV1] = []
    for instant in sorted({f.instant for f in facts if f.instant is not None}):
        if original.report_period_end is None or instant > original.report_period_end:
            return AwardDisclosureSelection(
                reason_codes=("MAPPING_PERIOD_AFTER_ORIGINAL",)
            )
        matches = tuple(f for f in facts if f.instant == instant)
        if len({f.namespace_uri for f in matches}) != 1:
            return AwardDisclosureSelection(
                reason_codes=("MAPPING_AWARD_DISCLOSURE_INVALID",)
            )
        try:
            candidates = parsed_facts_to_candidates(
                original.report.model_copy(update={"facts": matches}),
                source=original.source,
                issuer_id=original.source.cik,
                normalized_field=role,
            )
            selection = select_fact(candidates, original.decision_at)
        except SnapshotError as error:
            return AwardDisclosureSelection(reason_codes=(error.code,))
        if selection.fact is None:
            return AwardDisclosureSelection(
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
                        award_disclosure_scope=AWARD_DISCLOSURE_SCOPE,
                    ),
                ),
                rationale=AWARD_DISCLOSURE_POLICY,
            )
        )
    rules: AccountingRoleRules = IssuerAccountingRoleRuleSetV1(
        policy_version=AWARD_DISCLOSURE_POLICY,
        normalized_field=role,
        issuer_id=original.source.cik,
        accession_number=original.source.accession_number,
        raw_content_hash=original.source.content_hash,
        parser_input_hash=original.source.parser_input_hash,
        parser_fact_digest=fact_semantic_digest(original.report),
        unit=definition.unit,
        currency=definition.currency,
        periods=tuple(periods),
    )
    for period, fact in zip(periods, selected):
        try:
            evaluate_period_rule(rules, period, (fact,))
        except AccountingRoleError as error:
            return AwardDisclosureSelection(reason_codes=(error.code,))
    if security_id is not None:
        rules = AccountingRoleRuleSetV1.model_validate(
            {
                **rules.model_dump(exclude={"protocol", "security_id"}),
                "security_id": security_id,
            }
        )
    return AwardDisclosureSelection(rules=rules, selected=tuple(selected))
