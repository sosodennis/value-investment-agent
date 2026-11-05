"""External adapters for the Fundamental agent slice."""

from .fundamental_service_client import (
    FundamentalServiceClientSettings,
    HttpFundamentalServiceClient,
)

__all__ = ["FundamentalServiceClientSettings", "HttpFundamentalServiceClient"]
