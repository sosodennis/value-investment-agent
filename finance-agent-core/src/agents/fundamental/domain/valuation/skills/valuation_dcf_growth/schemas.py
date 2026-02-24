from pydantic import Field

from ..valuation_saas.schemas import SaaSParams


class DCFGrowthParams(SaaSParams):
    model_variant: str = Field(
        default="dcf_growth",
        description="Explicit model variant for growth DCF flow.",
    )
