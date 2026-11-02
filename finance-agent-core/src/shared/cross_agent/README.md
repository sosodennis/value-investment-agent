# `shared/cross_agent`

This package contains domain-neutral contracts that multiple agents use. The
current shared model is `CompanyProfile`, which lives in `domain/market_identity.py`.

Artifact persistence, artifact payload contracts, and typed artifact access belong
to `src/artifacts`. Agent repositories use its public contracts instead of adding
artifact-specific storage helpers to this package.
