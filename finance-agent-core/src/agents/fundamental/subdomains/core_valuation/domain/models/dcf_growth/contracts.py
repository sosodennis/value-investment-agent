from pydantic import Field

from ..saas.contracts import SaaSParams


class DCFGrowthParams(SaaSParams):
    model_variant: str = Field(
        default="dcf_growth",
        description="Explicit model variant for growth DCF flow.",
    )
