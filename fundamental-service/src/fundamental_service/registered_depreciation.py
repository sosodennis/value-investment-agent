"""Issuer/original-specific continuing D&A classifications, at reported precision.

This registry authorizes only the cited original fact multisets. It is not an
alias for aggregate D&A on an arbitrary issuer, filing, or parser result.
"""

from dataclasses import dataclass
import re

from .accounting_roles import (
    AccountingComponentV1,
    AccountingRoleError,
    evaluate_period_rule,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleRules,
    AccountingRoleRuleSetV1,
    DiscontinuedDepreciationExclusionV1,
    DiscontinuedDepreciationPassageV1,
    IssuerAccountingRoleRuleSetV1,
)
from .arelle_parser import fact_semantic_digest, ParsedXbrlFactV1
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import sha256_digest

DEPRECIATION = "us-gaap:DepreciationDepletionAndAmortization"
FIXED_ASSET_DEPRECIATION = "us-gaap:Depreciation"
ADJUSTED_DEPRECIATION = "registered:ContinuingDepreciationAndAmortization"
POLICY = "newmarket-original-continuing-depreciation-v1"


@dataclass(frozen=True)
class OriginalClassification:
    source_hash: str
    fact_digest: str
    continuing_years: tuple[int, ...]
    discontinued_years: tuple[int, ...]
    direct_concept: str = DEPRECIATION


# The source audit and scope rationale are in docs/accounting-role-evidence.md.
# Only identities/classifications are pinned; amounts always come from facts.
_ORIGINALS = {
    ("0001282637", "0001282637-15-000004"): OriginalClassification(
        "5e9510723b0fb3a20bc9a4f77d14cdbc984dffb2c327fb98388c60ae98ee5f7d",
        "fb3dfe48db99cd56e547a4b24349783f7d73f1b5fac7e0c4fb4d0a741ae591b3",
        (2014,),
        (2012, 2013),
    ),
    ("0001282637", "0001282637-16-000028"): OriginalClassification(
        "06be302baf2ecf9ff95ab87243df1f2a1cd63e9ababc969b89c4764be794e380",
        "87cdac62baffd9c6810d93bec52c418fef016931c445fca0771ec597d3bef5f0",
        (2014, 2015),
        (2013,),
    ),
    ("0001282637", "0001282637-17-000005"): OriginalClassification(
        "19247250d691d0625172f45ab484b7e6ad44b2b82462e6aff3ed956f03576422",
        "67ab534c782b3412c77d57cdc2e6dd42a2809924488d85ea6d975a0d09c706a1",
        (2014, 2015, 2016),
        (),
    ),
    ("0000724910", "0001376474-23-000283"): OriginalClassification(
        "26d95888105590690531f4b3c4da8ca910e6aa4e315f6372ed51c55459b0b05c",
        "1ce5d69c3a2b560110b3cfffba644b15125475ce3531a99bdc5a5f5fd35ef90e",
        (2022, 2023),
        (),
        FIXED_ASSET_DEPRECIATION,
    ),
    ("0000724910", "0001376474-24-000214"): OriginalClassification(
        "e337d87718577db631e61f5495c3c8f96304c0552161cb5054305967394c9dc6",
        "21c4ebca39e56c934edded6065b4ac78a0f451de96a540afe5d49726c53b01c1",
        (2023, 2024),
        (),
        FIXED_ASSET_DEPRECIATION,
    ),
}


def registered_depreciation_concept(original: OriginalIssuerEvidenceV1) -> str:
    """Choose a proposal from a matched original; selection still rechecks it."""
    entry = _ORIGINALS.get((original.source.cik, original.source.accession_number))
    if (
        entry is not None
        and original.source.content_hash == entry.source_hash
        and fact_semantic_digest(original.report) == entry.fact_digest
    ):
        return entry.direct_concept
    return DEPRECIATION


@dataclass(frozen=True)
class DepreciationSelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    rejected: tuple[tuple[ParsedXbrlFactV1, str], ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_registered_depreciation(
    original: OriginalIssuerEvidenceV1,
    *,
    adjusted: bool,
    source_concept: str = DEPRECIATION,
    security_id: str | None = None,
) -> DepreciationSelection:
    """Reproduce only the registered source classification, never infer absence."""
    source = original.source
    entry = _ORIGINALS.get((source.cik, source.accession_number))
    if entry is None or source.content_hash != entry.source_hash:
        return DepreciationSelection(reason_codes=("MAPPING_DA_SCOPE_UNREVIEWED",))
    if fact_semantic_digest(original.report) != entry.fact_digest:
        return DepreciationSelection(reason_codes=("MAPPING_DA_SOURCE_MISMATCH",))
    totals = tuple(
        f
        for f in sorted(original.report.facts, key=sha256_digest)
        if f.concept == DEPRECIATION and not f.dimensions and f.is_numeric
    )
    if not adjusted and source_concept != entry.direct_concept:
        return DepreciationSelection(
            rejected=tuple(
                (f, "MAPPING_DA_OPERATING_SCOPE_UNRESOLVED") for f in totals
            ),
            reason_codes=("MAPPING_DA_CONCEPT_SCOPE_UNREVIEWED",),
        )
    rejected = tuple(
        (f, "MAPPING_DA_DISCONTINUED_ADJUSTMENT_REQUIRED")
        for f in totals
        if f.period_end is not None and f.period_end.year in entry.discontinued_years
    )
    if not adjusted:
        direct = tuple(
            f
            for f in sorted(original.report.facts, key=sha256_digest)
            if f.concept == entry.direct_concept and not f.dimensions and f.is_numeric
        )
        if entry.direct_concept != DEPRECIATION:
            rejected = tuple(
                (f, "MAPPING_DA_DIFFERENT_ACCOUNTING_SCOPE") for f in totals
            )
        return DepreciationSelection(
            selected=tuple(
                f
                for f in direct
                if f.period_end is not None
                and f.period_end.year in entry.continuing_years
            ),
            rejected=rejected,
        )
    if not entry.discontinued_years:
        return DepreciationSelection(reason_codes=("MAPPING_NO_ELIGIBLE_OBSERVATIONS",))
    notes = tuple(
        f
        for f in original.report.facts
        if f.concept == "us-gaap:SegmentReportingDisclosureTextBlock"
        and not f.is_numeric
        and not f.dimensions
    )
    if len(notes) != 1:
        return DepreciationSelection(
            reason_codes=("MAPPING_DA_CLASSIFICATION_MISSING",)
        )
    note = notes[0]
    quotes = re.findall(
        rf"The amounts? for {max(entry.discontinued_years)}.*?Consolidated Statements of Income\.",
        note.value,
        re.S,
    )
    if len(quotes) != 1:
        return DepreciationSelection(
            reason_codes=("MAPPING_DA_CLASSIFICATION_MISSING",)
        )
    periods = []
    selected = {sha256_digest(note): note}
    for year in entry.discontinued_years:
        bases = tuple(
            f for f in totals if f.period_end is not None and f.period_end.year == year
        )
        exclusions = tuple(
            f
            for f in original.report.facts
            if f.concept == DEPRECIATION
            and f.is_numeric
            and dict(f.dimensions).get("us-gaap:IncomeStatementLocationAxis")
            == "neu:IncomeLossFromOperationsOfDiscontinuedBusinessNetOfTaxMember"
            and f.period_end is not None
            and f.period_end.year == year
        )
        if len(bases) != 1 or len(exclusions) != 1:
            return DepreciationSelection(
                reason_codes=("MAPPING_DA_COMPONENTS_INCOMPLETE",)
            )
        base, excluded = bases[0], exclusions[0]
        assert base.period_start is not None and base.period_end is not None
        selected.update({sha256_digest(f): f for f in (base, excluded)})
        periods.append(
            AccountingPeriodRuleV1(
                period=AccountingPeriodV1(
                    period_start=base.period_start, period_end=base.period_end
                ),
                disposition="derived",
                components=(
                    AccountingComponentV1(parsed_fact_digest=sha256_digest(base)),
                    AccountingComponentV1(
                        parsed_fact_digest=sha256_digest(excluded),
                        sign=-1,
                        discontinued_depreciation_exclusion=DiscontinuedDepreciationExclusionV1(
                            dimensions=excluded.dimensions,
                            consolidated_base_fact_digest=sha256_digest(base),
                            classification_passage=DiscontinuedDepreciationPassageV1(
                                parsed_fact_digest=sha256_digest(note),
                                exact_quote=quotes[0],
                            ),
                        ),
                    ),
                ),
                rationale=POLICY
                + ": reported continuing D&A; rounded exclusion remains rounded",
            )
        )
    rules: AccountingRoleRules = IssuerAccountingRoleRuleSetV1(
        policy_version=POLICY,
        normalized_field="depreciation_and_amortization",
        issuer_id=source.cik,
        accession_number=source.accession_number,
        raw_content_hash=source.content_hash,
        parser_input_hash=source.parser_input_hash,
        parser_fact_digest=entry.fact_digest,
        unit="iso4217:USD",
        currency="USD",
        periods=tuple(periods),
    )
    try:
        for rule in rules.periods:
            evaluate_period_rule(
                rules, rule, tuple(selected[k] for k in rule.source_references())
            )
    except AccountingRoleError as error:
        return DepreciationSelection(reason_codes=(error.code,))
    if security_id is not None:
        rules = AccountingRoleRuleSetV1.model_validate(
            {
                **rules.model_dump(exclude={"protocol", "security_id"}),
                "security_id": security_id,
            }
        )
    return DepreciationSelection(
        rules=rules,
        selected=tuple(selected[k] for k in sorted(selected)),
    )
