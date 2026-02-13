from __future__ import annotations

from src.agents.debate.domain.models import EvidenceFact
from src.agents.debate.domain.services import compress_financial_data
from src.common.traceable import ManualProvenance, XBRLProvenance
from src.common.types import JSONObject


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
    signal_raw = ta_data.get("signal_state")
    signal = signal_raw if isinstance(signal_raw, dict) else {}
    if not signal:
        return []

    fact_id = f"T{start_index:03d}"
    return [
        EvidenceFact(
            fact_id=fact_id,
            source_type="technicals",
            source_weight="HIGH",
            summary=f"Technical Signal: {signal.get('direction')} (Z-Score: {signal.get('z_score')})",
            value=signal.get("z_score"),
            provenance=ManualProvenance(
                description=f"Technical Signal (Z-Score Analysis) from Artifact {ta_artifact_id}",
                author="TechnicalAnalyst",
            ),
        )
    ]


def summarize_facts_by_source(facts: list[EvidenceFact]) -> dict[str, int]:
    return {
        "financials": len([fact for fact in facts if fact.source_type == "financials"]),
        "news": len([fact for fact in facts if fact.source_type == "news"]),
        "technicals": len([fact for fact in facts if fact.source_type == "technicals"]),
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
