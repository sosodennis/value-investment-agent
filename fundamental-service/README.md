# Fundamental service

This directory is the documentation-only home of the independently deployable Fundamental domain service. The service has no runtime package yet.

Read the [Fundamental service target state](docs/fundamental-enterprise-grade-target-state.md) for the only normative definition of the service's data contracts, model registry, calculations, calibration, provenance, verification, and delivery stages.

The service will own its source snapshots, point-in-time facts, model definitions, deterministic calculations, calibration artifacts, replay, and cache. The existing agent will call the service through a versioned API after the service passes the release gate for its declared coverage profile. The service must not import the existing agent's private implementation or share its valuation database.

Keep this package documentation-only until implementation begins under an approved change. Do not add a second design specification here. Update the canonical target-state document when a domain contract or release rule changes.
