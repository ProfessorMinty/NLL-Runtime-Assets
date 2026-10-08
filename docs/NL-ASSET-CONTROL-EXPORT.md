# NL Asset Control Export Requirements

This document defines the export side of the reviewed runtime-publication
contract owned by **NL Asset Control**.

## Goal

NL Asset Control transforms approved private logical assets into validated,
content-addressed derivative objects for R2 and reviewed public manifests for
this repository without exposing private source-library state.

## Proposed operator workflow

```text
Publish / Export

1. Validate Candidates
2. Build Web Derivatives
3. Build Runtime Manifests
4. Validate Staged Candidate
5. Upload and Verify Immutable R2 Objects
6. Propose Reviewed Artifact Manifests
7. Select Through a Separate Reviewed Pointer Operation
```

The exporter does not copy derivative bytes into a Git checkout or push directly
to `main`. GitHub changes go through the purpose-limited transactional publisher
and reviewed release lanes defined in `docs/PUBLISHING-CONTRACT.md`.

## Configuration

The exporter should not hard-code one workstation checkout path.

Persist configurable publishing settings such as:

- pinned runtime repository owner/name and verified numeric identity;
- pinned R2 bucket/CDN configuration;
- certified GitHub App installation identity;
- staging path;
- enabled derivative formats;
- raster derivative sizes;
- manifest schema version;
- runtime path policy.

Machine-specific configuration belongs in private/local application state, not in generated public manifests.

## Candidate validation

Before building output, validate each selected logical asset for:

- stable public asset ID;
- approved asset state;
- publishable rights state;
- accessibility role;
- required alt text for informative assets;
- required public credit when applicable;
- at least one source variant suitable for derivative generation;
- absence of blocking curation/grouping errors.

Never-published invalid candidates should be reported clearly and may be
excluded only under an explicitly reviewed partial-candidate policy. A stable
ID present in any predecessor release may never be omitted: the transaction
must fail unless that ID is emitted as either a valid retained `READY` record or
a valid `UNAVAILABLE` tombstone.

The default should be **fail closed**.

## Stable IDs

Published IDs must follow the contract in `docs/PUBLISHING-CONTRACT.md`.

NL Asset Control should maintain the public ID as durable human-controlled metadata rather than regenerating it from mutable filenames on every export.

Once an ID has been published, changing display name, source filename, derivative format, or source pack must not silently create a replacement identity.

## Derivative generation

The exporter should generate only browser-safe derivatives approved by policy.

Expected initial targets:

- SVG when an approved vector source can be safely delivered;
- WebP raster derivatives;
- PNG only when required by source characteristics or consumer compatibility.

Raster output should be generated from the best suitable private master, not by repeatedly transcoding an already-downscaled runtime derivative.

Derivative generation should be deterministic where practical.

`READY` is blocked until exact-byte safety validation exists for the chosen
format. SVG policy rejects script, `foreignObject`, event handlers, external
links, CSS `@import`, and external `url(...)` loads. GLTF/GLB policy requires a
reviewed parser and a self-contained graph with no external URI. The private
byte-safety receipt binds exact SHA-256 plus validator and policy versions;
extension and MIME metadata alone are not approval.

## Runtime object identities

Every derivative byte is published to an immutable content-addressed R2 key:

```text
objects/sha256/<first-two-sha256-characters>/<sha256>.<extension>
```

The corresponding public URL is:

```text
https://cdn.nlightlabs.com/objects/sha256/<first-two-sha256-characters>/<sha256>.<extension>
```

Derivative bytes must not be written into this Git repository. Its only
permitted `assets/` entry is `assets/.gitkeep`. No generated object or manifest
may contain an absolute local path such as:

```text
<private-library-root>/...
```

The object key is derived from the exact derivative bytes rather than from a
vendor filename or mutable display name. Stable logical identity remains in the
manifest's asset ID and asset-version fields.

## Integrity metadata

For every generated derivative, calculate after generation:

- byte size;
- SHA-256;
- MIME type;
- positive raster width and height for WebP, PNG, JPG, and JPEG;
- null or paired positive dimensions only where dimensions are genuinely not
  applicable.

The manifest must describe the actual staged file, not predicted values.
Apply the permanent V1 limits before any upload: SVG 2 MiB; WebP/PNG/JPG/JPEG
16 MiB; GLTF 8 MiB; GLB 64 MiB; no object above 64 MiB; at most 8 GiB of unique
objects in one release; and at most 16 MiB for each JSON artifact. Hashing,
upload, and remote verification stream bytes rather than buffering the full
candidate.

## Reviewed release generation

For a new release ID, generate exactly the artifact-lane files:

```text
manifests/releases/<release-id>/release.json
manifests/releases/<release-id>/consumer-catalog.json
```

Rules:

- output must conform to the schemas in `schemas/`;
- catalog records must be sorted by stable ID using the owning ordinal contract;
- the descriptor and catalog must enumerate exactly the same immutable R2
  object evidence;
- counts must match record arrays;
- use `/` for runtime paths on every platform;
- private provenance must not leak into public records;
- generated JSON must use the canonical byte format defined by the immutable
  identity contract.

The legacy root manifests (`manifests/index.json`, `assets.json`,
`collections.json`, and `themes.json`) remain frozen compatibility authority.
This release exporter must not regenerate them. Any future legacy-consumer
cutover requires its own reviewed contract, recovery proof, and purpose lane.

## Staging and transaction safety

Do not write half a publish over a known-good release, current pointer, or R2
object identity.

Recommended flow:

1. Create/clean an isolated staging directory.
2. Generate all candidate derivatives there.
3. Generate the immutable release descriptor and consumer catalog there.
4. Validate schemas and cross-references.
5. Verify derivative hashes and byte counts.
6. Compare the staged catalog against the reviewed predecessor catalog and
   verify any already-present R2 objects byte-for-byte.
7. Present a publish summary.
8. Upload missing immutable objects to R2 and verify their remote identity.
9. Propose only the completed reviewed manifests to the repository artifact
   lane; select them later through the separate current-pointer lane.

If generation or validation fails, leave the previous manifest release and
current pointer intact. Upload occurs only after the exact derivative has passed
its rights and byte-safety approval. Any uploaded content-addressed object that
is not selected remains absent from the reviewed consumer catalog, but its CDN
key may still be reachable; it is not harmless or an approval substitute.
Inventory every such orphan as recoverable incident evidence and retain the
authorized quarantine/purge path. A partial release must never become
consumer-discoverable through the reviewed manifest.

## Existing published assets

The exporter must reconcile against prior public IDs.

It should be able to distinguish:

- unchanged asset;
- changed derivative of same logical asset;
- newly published asset;
- deprecated asset;
- asset blocked from further publication.

Do not reuse a retired ID for unrelated content.

## Cleanup policy

Immutable R2 objects and reviewed release files no longer referenced by the
current pointer must not be deleted by routine publication.

Retain the stable ID in successor catalogs. A still-deliverable retirement may
remain `READY` and deprecated; a blocked asset must become an `UNAVAILABLE`
tombstone with no variants. Permanent object purge is a separate,
high-risk recovery/rights operation with its own reference analysis and approval;
it is not an exporter cleanup step.

A preview of additions, new versions, deprecations, and pointer effects should
be shown before publication.

## Publish summary

The UI should report at least:

- candidate assets;
- publishable assets;
- blocked assets;
- new assets;
- changed assets;
- unchanged assets;
- deprecated/removed assets;
- derivatives generated;
- validation errors;
- output bytes;
- manifest/schema version.

## Manual Refresh is not workflow

As with the rest of NL Asset Control, successful publishing operations should update application state automatically. Manual refresh controls may exist for recovery but should not be required in the normal publish path.

## Implementation boundary

Candidate generation and validation may complete without any external mutation.
External writes belong only to the separately enabled transactional publisher:
immutable R2 upload and verification, a purpose-limited artifact pull request,
an immutable annotated tag, and a separate purpose-limited pointer pull request.

Keep that publisher disabled until its credential, repository-protection,
recovery, rollback, and end-to-end authorization gates have all passed. Merely
building or staging a candidate never makes it current.
