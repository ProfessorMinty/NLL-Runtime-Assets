# Immutable identity and release contract

`asset-registry-v2.schema.json` and `runtime-release-v1.schema.json` define the next immutable release format. They do not change the current manifest pointer or publish a release.

- `id` and `runtimeId` are the permanent logical runtime identity. Mutable names, tags, classifications, and source paths never generate or replace them.
- `assetVersion` is a SHA-256 identity over the released semantic metadata and ordered variant set.
- `objectKey` is derived only from verified bytes as `objects/sha256/<first-two>/<full-sha256>.<extension>`.
- `legacyPath` records the frozen predecessor path. Existing legacy bytes remain available and are never overwritten by the immutable publisher.
- `path` remains the legacy compatibility path during migration. New consumers use the released `objectKey` through a versioned Project/Consumer Export.
- A release records its predecessor, exact Git commit, manifest and object hashes, candidate identity, publisher identity, and rollback receipt identity.

The current schema-v1 manifests and legacy paths remain valid until a reviewed pointer-only release cutover. Adding these schemas is not that cutover.
