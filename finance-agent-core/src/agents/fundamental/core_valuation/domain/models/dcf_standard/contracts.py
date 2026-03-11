from pydantic import Field

from ..saas.contracts import SaaSParams


class DCFStandardParams(SaaSParams):
    model_variant: str = Field(
        default="dcf_standard",
        description="Explicit model variant for standard DCF flow.",
    )
