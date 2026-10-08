# Immutable identity and release contract

`asset-registry-v2.schema.json`, `nl-asset-consumer-catalog-v1.schema.json`,
`runtime-release-v1.schema.json`, and `runtime-current-pointer-v1.schema.json`
define the next immutable release format. They do not create a current pointer
or publish a release.

- V1 release directories and annotated tags use
  `runtime-v1-YYYY.MM.DD.N`. Future contract versions use disjoint identities
  and manifest roots; they do not reinterpret accepted V1 artifacts.
- `id` and `runtimeId` are the permanent logical runtime identity. Mutable names, tags, classifications, and source paths never generate or replace them.
- Public `assetVersion` is SHA-256 over canonical
  `NLAssetConsumerAssetVersionMaterialV1`: browser-safe name/type/subtype,
  bounded taxonomy, accessibility/credit, readiness/deprecation/fallback,
  sanitized provenance, and ordered immutable variant evidence. String keys and
  sorted string sets use .NET ordinal UTF-16 code-unit order, including for
  supplementary-plane characters; unpaired UTF-16 surrogates are invalid.
  `releaseId`, `generatedAt`, and the derived CDN URL are excluded, so transport selection
  cannot rewrite semantic identity. Canonical JSON uses sorted keys, two-space
  indentation, System.Text.Json-compatible escaping, and one final LF.
- `objectKey` is derived only from verified bytes as `objects/sha256/<first-two>/<full-sha256>.<extension>`.
- `legacyPath` records the frozen predecessor path. In ordinary operation,
  existing legacy bytes remain available and are never overwritten or deleted
  by the immutable publisher. The separately owner-authorized delivery-stop
  quarantine/purge runbook remains the exception for rights, privacy, safety,
  legal, or integrity incidents.
- `path` remains the legacy compatibility path during migration. New consumers use the released `objectKey` through a versioned Project/Consumer Export.
- A release records its predecessor, exact catalog and object evidence,
  precomputed source-candidate identity, publisher identity, the authenticated
  pre-publication authorization identity, and the publication transaction's
  recovery-authorization identity. Neither public field claims publication
  completed, and the recovery authorization is not standing permission for a
  later pointer rollback. It cannot contain its own Git commit without becoming
  self-referential. The separate staging-descriptor hash binds the completed
  release.json, catalog, and object set; it is not stored inside release.json.
- The separately reviewed current pointer and annotated tag record the exact
  already-merged release-artifact commit, catalog path/hash/schema, predecessor,
  and pre-publication authorization identity. Completed transition receipts
  remain private.
- The consumer catalog is the narrow browser-safe released view. It exposes
  permanent IDs, immutable versions and CDN variants, not private library paths,
  evidence, notes, credentials, or masters.
- Stable IDs remain present after retirement. `READY` plus `deprecated: true`
  remains renderable only for existing pinned dependencies and is excluded from
  new selection. A blocked asset is an `UNAVAILABLE`, deprecated tombstone with
  no variants and either a `READY`, nondeprecated fallback or no fallback.

The current schema-v1 manifests and legacy paths remain valid until a reviewed pointer-only release cutover. Adding these schemas is not that cutover.
