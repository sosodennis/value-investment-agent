from ..engine.graphs.dcf_standard import create_dcf_standard_graph
from ..models.dcf_standard.contracts import DCFStandardParams
from .dcf_variant_calculator import (
    DcfMonteCarloPolicy,
    calculate_dcf_variant_valuation,
)

_STANDARD_MONTE_CARLO_POLICY = DcfMonteCarloPolicy(
    growth_std_scale=0.8,
    growth_std_min=0.005,
    growth_clip_min=-0.25,
    growth_clip_max=0.25,
    margin_std_scale=0.8,
    margin_std_min=0.005,
    margin_clip_min=-0.12,
    margin_clip_max=0.12,
    wacc_min=0.03,
    wacc_max=0.30,
    terminal_min=-0.01,
    terminal_max=0.05,
)


def calculate_dcf_standard_valuation(
    params: DCFStandardParams,
) -> dict[str, float | str | dict[str, object]]:
    return calculate_dcf_variant_valuation(
        params,
        graph_factory=create_dcf_standard_graph,
        monte_carlo_policy=_STANDARD_MONTE_CARLO_POLICY,
    )
