from pydantic import Field

from ..valuation_saas.schemas import SaaSParams


class DCFStandardParams(SaaSParams):
    model_variant: str = Field(
        default="dcf_standard",
        description="Explicit model variant for standard DCF flow.",
    )
