from ..engine.graphs.dcf_growth import create_dcf_growth_graph
from ..models.dcf_growth.contracts import DCFGrowthParams
from .dcf_variant_calculator import (
    DcfMonteCarloPolicy,
    calculate_dcf_variant_valuation,
)

_GROWTH_MONTE_CARLO_POLICY = DcfMonteCarloPolicy(
    growth_std_scale=1.2,
    growth_std_min=0.01,
    growth_clip_min=-0.35,
    growth_clip_max=0.35,
    margin_std_scale=1.2,
    margin_std_min=0.01,
    margin_clip_min=-0.18,
    margin_clip_max=0.18,
    wacc_min=0.03,
    wacc_max=0.35,
    terminal_min=-0.01,
    terminal_max=0.06,
)


def calculate_dcf_growth_valuation(
    params: DCFGrowthParams,
) -> dict[str, float | str | dict[str, object]]:
    return calculate_dcf_variant_valuation(
        params,
        graph_factory=create_dcf_growth_graph,
        monte_carlo_policy=_GROWTH_MONTE_CARLO_POLICY,
    )
