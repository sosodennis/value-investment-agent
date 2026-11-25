from collections.abc import Mapping
from dataclasses import dataclass

from .fiscal_validation_contracts import FISCAL_TAXONOMY_CACHE_SHA256
from .source_acquisition import (
    parse_supported_filing_forms,
    parse_supported_filing_years,
)

_CACHE_DIR = "FUNDAMENTAL_FISCAL_SEC_TAXONOMY_CACHE_DIR"
_MANIFEST_ID = "FUNDAMENTAL_FISCAL_SEC_TAXONOMY_MANIFEST_ID"
_VERSION = "FUNDAMENTAL_FISCAL_SEC_TAXONOMY_VERSION"
_CACHE_HASH = "FUNDAMENTAL_FISCAL_SEC_TAXONOMY_CACHE_SHA256"
_FILING_YEARS = "FUNDAMENTAL_FISCAL_SEC_SUPPORTED_FILING_YEARS"
_FILING_FORMS = "FUNDAMENTAL_FISCAL_SEC_SUPPORTED_FILING_FORMS"


@dataclass(frozen=True)
class FiscalRuntimeConfig:
    taxonomy_cache_dir: str
    taxonomy_manifest_id: str
    taxonomy_version: str
    taxonomy_cache_sha256: str
    supported_filing_years: tuple[int, ...]
    supported_filing_forms: tuple[str, ...]

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "FiscalRuntimeConfig | None":
        names = (
            _CACHE_DIR,
            _MANIFEST_ID,
            _VERSION,
            _CACHE_HASH,
            _FILING_YEARS,
            _FILING_FORMS,
        )
        if not any(name in environ for name in names):
            return None
        missing = [name for name in names if not environ.get(name, "").strip()]
        if missing:
            raise ValueError(f"Missing fiscal runtime settings: {', '.join(missing)}")
        taxonomy_cache_sha256 = environ[_CACHE_HASH].strip()
        if taxonomy_cache_sha256 != FISCAL_TAXONOMY_CACHE_SHA256:
            raise ValueError(f"{_CACHE_HASH} must match the pinned fiscal cache")
        try:
            years = parse_supported_filing_years(environ[_FILING_YEARS])
        except ValueError:
            raise ValueError(
                f"{_FILING_YEARS} must contain valid SEC filing years"
            ) from None
        try:
            forms = parse_supported_filing_forms(environ[_FILING_FORMS])
        except ValueError:
            raise ValueError(
                f"{_FILING_FORMS} must contain valid SEC filing forms"
            ) from None
        assert years is not None and forms is not None
        return cls(
            taxonomy_cache_dir=environ[_CACHE_DIR].strip(),
            taxonomy_manifest_id=environ[_MANIFEST_ID].strip(),
            taxonomy_version=environ[_VERSION].strip(),
            taxonomy_cache_sha256=taxonomy_cache_sha256,
            supported_filing_years=years,
            supported_filing_forms=forms,
        )
