# `shared/artifacts`

This package holds versioned artifact payload schemas and provenance contracts
used by the artifact capability and multiple agents. It does not own artifact
storage, contract registration, API projection, or artifact-specific access rules.

Keep helpers in this package domain-neutral. Move a schema into its owning
feature when it no longer has multiple real consumers. The ownership fitness
test checks those dependencies.
