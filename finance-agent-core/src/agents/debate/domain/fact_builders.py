from __future__ import annotations

from collections.abc import Mapping

from src.agents.debate.domain.entities import EvidenceFact
from src.agents.debate.domain.report_compression_service import (
    compress_financial_data,
)
from src.agents.fundamental.domain.shared.contracts.traceable import (
    ManualProvenance,
    XBRLProvenance,
)
from src.shared.kernel.types import JSONObject


def build_financial_facts(
    reports: list[JSONObject], *, start_index: int = 1
) -> list[EvidenceFact]:
    facts: list[EvidenceFact] = []
    next_index = start_index

    for report in reports:
        base_raw = report.get("base")
        if not isinstance(base_raw, dict):
            continue
        fiscal_year_field = base_raw.get("fiscal_year")
        fiscal_year = (
            fiscal_year_field.get("value", "N/A")
            if isinstance(fiscal_year_field, dict)
            else "N/A"
        )
        compressed = compress_financial_data([report])
        if not compressed:
            continue
        metrics_raw = compressed[0].get("metrics", {})
        if not isinstance(metrics_raw, dict):
            continue

        for metric_name, value in metrics_raw.items():
            fact_id = f"F{next_index:03d}"
            next_index += 1

            provenance = _financial_provenance(
                base=base_raw,
                extension=report.get("extension"),
                metric_name=metric_name,
                fiscal_year=str(fiscal_year),
            )

            facts.append(
                EvidenceFact(
                    fact_id=fact_id,
                    source_type="financials",
                    source_weight="HIGH",
                    summary=f"[{fiscal_year}] {metric_name.replace('_', ' ').title()}: {value}",
                    value=value,
                    period=str(fiscal_year),
                    provenance=provenance,
                )
            )
    return facts


def build_news_facts(
    news_items: list[JSONObject], *, start_index: int = 1
) -> list[EvidenceFact]:
    facts: list[EvidenceFact] = []
    next_index = start_index

    for item in news_items:
        analysis_raw = item.get("analysis")
        analysis = analysis_raw if isinstance(analysis_raw, dict) else {}
        key_facts = analysis.get("key_facts", []) or [
            {"content": analysis.get("summary")}
        ]

        source_raw = item.get("source")
        source_name = (
            source_raw.get("name", "Unknown")
            if isinstance(source_raw, dict)
            else "Unknown"
        )
        published_at = item.get("published_at", "N/A")
        pub_date = str(published_at)[:10]

        for fact_item in key_facts:
            content = (
                fact_item.get("content")
                if isinstance(fact_item, dict)
                else str(fact_item)
            )
            if not content:
                continue
            fact_id = f"N{next_index:03d}"
            next_index += 1
            facts.append(
                EvidenceFact(
                    fact_id=fact_id,
                    source_type="news",
                    source_weight="MEDIUM",
                    summary=f"({pub_date}) {source_name}: {content}",
                    provenance=ManualProvenance(
                        description=f"News: {item.get('title')}"
                    ),
                )
            )
    return facts


def build_technical_facts(
    ta_data: JSONObject | None,
    *,
    ta_artifact_id: str | None,
    start_index: int = 1,
) -> list[EvidenceFact]:
    if ta_data is None:
        return []

    facts: list[EvidenceFact] = []
    next_index = start_index

    direction = _coerce_text(ta_data.get("direction"))
    risk_level = _coerce_text(ta_data.get("risk_level"))
    confidence = _coerce_float(ta_data.get("confidence"))
    if direction is not None or risk_level is not None or confidence is not None:
        facts.append(
            EvidenceFact(
                fact_id=f"T{next_index:03d}",
                source_type="technicals",
                source_weight="HIGH",
                summary=(
                    f"Technical direction: {direction or 'unknown'}, "
                    f"risk level: {risk_level or 'n/a'}, "
                    f"confidence: {confidence if confidence is not None else 'n/a'}"
                ),
                value=confidence,
                provenance=ManualProvenance(
                    description=f"Technical summary from Artifact {ta_artifact_id}",
                    author="TechnicalAnalyst",
                ),
            )
        )
        next_index += 1

    summary_tags = ta_data.get("summary_tags")
    if isinstance(summary_tags, list) and summary_tags:
        facts.append(
            EvidenceFact(
                fact_id=f"T{next_index:03d}",
                source_type="technicals",
                source_weight="MEDIUM",
                summary=f"Technical summary tags: {', '.join([str(tag) for tag in summary_tags])}",
                value=", ".join([str(tag) for tag in summary_tags]),
                provenance=ManualProvenance(
                    description=f"Technical tags from Artifact {ta_artifact_id}",
                    author="TechnicalAnalyst",
                ),
            )
        )
        next_index += 1

    diagnostics_raw = ta_data.get("diagnostics")
    diagnostics = diagnostics_raw if isinstance(diagnostics_raw, Mapping) else {}
    degraded_reasons = diagnostics.get("degraded_reasons")
    if isinstance(degraded_reasons, list) and degraded_reasons:
        facts.append(
            EvidenceFact(
                fact_id=f"T{next_index:03d}",
                source_type="technicals",
                source_weight="LOW",
                summary=f"Technical data degraded: {', '.join([str(reason) for reason in degraded_reasons])}",
                value=", ".join([str(reason) for reason in degraded_reasons]),
                provenance=ManualProvenance(
                    description=f"Technical diagnostics from Artifact {ta_artifact_id}",
                    author="TechnicalAnalyst",
                ),
            )
        )
        next_index += 1

    return facts


def build_valuation_facts(
    valuation_preview: JSONObject | None,
    *,
    start_index: int = 1,
) -> list[EvidenceFact]:
    if valuation_preview is None:
        return []

    facts: list[EvidenceFact] = []
    next_index = start_index

    model_type = _coerce_text(valuation_preview.get("model_type"))
    if model_type is not None:
        facts.append(
            EvidenceFact(
                fact_id=f"V{next_index:03d}",
                source_type="valuation",
                source_weight="HIGH",
                summary=f"Valuation model selected: {model_type}",
                value=model_type,
                provenance=ManualProvenance(
                    description="Fundamental valuation preview",
                    author="FundamentalAnalyst",
                ),
            )
        )
        next_index += 1

    intrinsic_value = _coerce_float(valuation_preview.get("intrinsic_value"))
    if intrinsic_value is not None:
        facts.append(
            EvidenceFact(
                fact_id=f"V{next_index:03d}",
                source_type="valuation",
                source_weight="HIGH",
                summary=f"Intrinsic value estimate: ${intrinsic_value:.2f}",
                value=intrinsic_value,
                units="USD/share",
                provenance=ManualProvenance(
                    description="Fundamental valuation preview",
                    author="FundamentalAnalyst",
                ),
            )
        )
        next_index += 1

    upside_potential = _coerce_float(valuation_preview.get("upside_potential"))
    if upside_potential is not None:
        upside_pct = upside_potential * 100.0
        facts.append(
            EvidenceFact(
                fact_id=f"V{next_index:03d}",
                source_type="valuation",
                source_weight="HIGH",
                summary=f"Upside potential vs current price: {upside_pct:.2f}%",
                value=upside_pct,
                units="percent",
                provenance=ManualProvenance(
                    description="Fundamental valuation preview",
                    author="FundamentalAnalyst",
                ),
            )
        )
        next_index += 1

    distribution_scenarios = valuation_preview.get("distribution_scenarios")
    scenario_specs = (
        ("bear", "P5 (Bear)"),
        ("base", "P50 (Base)"),
        ("bull", "P95 (Bull)"),
    )
    if isinstance(distribution_scenarios, Mapping):
        for scenario_key, scenario_label in scenario_specs:
            scenario_raw = distribution_scenarios.get(scenario_key)
            if not isinstance(scenario_raw, Mapping):
                continue
            price = _coerce_float(scenario_raw.get("price"))
            if price is None:
                continue
            facts.append(
                EvidenceFact(
                    fact_id=f"V{next_index:03d}",
                    source_type="valuation",
                    source_weight="MEDIUM",
                    summary=f"Valuation distribution {scenario_label}: ${price:.2f}",
                    value=price,
                    units="USD/share",
                    provenance=ManualProvenance(
                        description="Fundamental valuation distribution preview",
                        author="FundamentalAnalyst",
                    ),
                )
            )
            next_index += 1

    return facts


def summarize_facts_by_source(facts: list[EvidenceFact]) -> dict[str, int]:
    return {
        "financials": len([fact for fact in facts if fact.source_type == "financials"]),
        "news": len([fact for fact in facts if fact.source_type == "news"]),
        "technicals": len([fact for fact in facts if fact.source_type == "technicals"]),
        "valuation": len([fact for fact in facts if fact.source_type == "valuation"]),
    }


def render_strict_facts_registry(facts: list[EvidenceFact]) -> str:
    return "FACTS_REGISTRY (STRICT CITATION REQUIRED):\n" + "\n".join(
        [f"[{fact.fact_id}] {fact.summary}" for fact in facts]
    )


def _financial_provenance(
    *,
    base: dict[str, object],
    extension: object,
    metric_name: str,
    fiscal_year: str,
) -> XBRLProvenance | ManualProvenance:
    prov_raw = base.get(metric_name, {})
    prov_candidate = prov_raw.get("provenance") if isinstance(prov_raw, dict) else None
    if not prov_candidate and isinstance(extension, dict):
        ext_field = extension.get(metric_name, {})
        if isinstance(ext_field, dict):
            prov_candidate = ext_field.get("provenance")

    if isinstance(prov_candidate, dict):
        return XBRLProvenance(
            concept=str(prov_candidate.get("concept") or metric_name),
            period=str(prov_candidate.get("period") or fiscal_year),
        )
    return ManualProvenance(description=f"Extracted from {fiscal_year} report")


def _coerce_text(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _coerce_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    if isinstance(value, Mapping):
        return _coerce_float(value.get("value"))
    return None
