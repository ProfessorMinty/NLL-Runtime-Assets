# NL Asset Control Export Requirements

This document is the implementation target for the future **Publish / Repository Export** subsystem in NL Asset Control.

## Goal

NL Asset Control should be able to transform approved private logical assets into a complete, validated public runtime package for this repository without exposing private source-library state.

## Proposed operator workflow

```text
Publish / Export

1. Validate Candidates
2. Build Web Derivatives
3. Build Runtime Manifests
4. Validate Staged Package
5. Stage to Repository
```

A manual repository commit/push may remain outside the application initially. Repository writes should not be introduced until local generation and staging are proven safe and repeatable.

## Configuration

The exporter should not hard-code one workstation checkout path.

Persist configurable publishing settings such as:

- local `NLL-Runtime-Assets` repository path;
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

Invalid candidates should be reported clearly and excluded from publication unless the entire publish is configured to fail as a transaction.

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

## Runtime paths

Runtime output must use repository-relative forward-slash paths under:

```text
assets/
```

No generated file or manifest may contain an absolute local path such as:

```text
E:\Assets\...
```

The exporter should use predictable collision-safe paths based primarily on stable asset identity rather than raw vendor filenames.

## Integrity metadata

For every generated derivative, calculate after generation:

- byte size;
- SHA-256;
- MIME type;
- raster width/height when applicable.

The manifest must describe the actual staged file, not predicted values.

## Manifest generation

Generate:

```text
manifests/index.json
manifests/assets.json
manifests/collections.json
manifests/themes.json
```

Rules:

- output must conform to the schemas in `schemas/`;
- records must be sorted by stable ID;
- collection/theme references must resolve;
- counts must match record arrays;
- use `/` for runtime paths on every platform;
- private provenance must not leak into public records;
- generated JSON should use consistent formatting and line endings.

## Staging and transaction safety

Do not write half a publish directly over a known-good repository tree.

Recommended flow:

1. Create/clean an isolated staging directory.
2. Generate all candidate derivatives there.
3. Generate all manifests there.
4. Validate schemas and cross-references.
5. Verify derivative hashes and byte counts.
6. Compare staged output against current repository output.
7. Present a publish summary.
8. Promote/stage the complete validated output into the repository working tree.

If generation or validation fails, leave the previous repository output intact.

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

Generated files no longer referenced by the new manifest should not be deleted blindly.

Before removal, confirm that the asset is intentionally deprecated/removed and that the cleanup operation is part of the validated publish plan.

A preview of adds, changes, and removals should be shown before destructive staging.

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

## First implementation boundary

The first safe implementation should stop after **validated staging into a local repository checkout**.

Do not automatically commit, tag, release, or push to GitHub until generation, validation, diffing, and rollback behavior have been proven in real use.
