# Edublogs Consumer Notes

This repository is consumable by Hughes Room Views and other browser runtimes
without exposing private asset-library state. Git publishes reviewed semantic
manifests; Cloudflare R2 and `cdn.nlightlabs.com` publish derivative bytes.

## V1 discovery and pinning

The reviewed current pointer is:

```text
manifests/releases/current.json
```

It is intentionally absent until the first authorized pointer selection. A
production consumer integration should resolve it during that consumer's own
reviewed build/publication process, validate it against the pointer schema, and
then pin the returned `releaseId`, `releaseArtifactCommit`, `catalogPath`, and
`catalogSha256` in the consumer release. It must not silently follow `main` on
every classroom page load.

Load the selected consumer catalog from the exact 40-character
`releaseArtifactCommit`, for example:

```text
https://raw.githubusercontent.com/ProfessorMinty/NLL-Runtime-Assets/<releaseArtifactCommit>/<catalogPath>
```

Verify the exact catalog bytes against `catalogSha256`. The commit-pinned
catalog, not a mutable branch and not R2, is semantic authority.

## Resolution flow

A V1 consumer resolves an asset in this order:

1. Use the consumer release's reviewed, pinned pointer receipt.
2. Load and hash-verify the commit-pinned `consumer-catalog.json`.
3. Resolve the permanent `assetId` and retain its `assetVersion` as dependency
   identity.
4. Require `readinessStatus: READY`. If it is `UNAVAILABLE`, use only a
   verified `READY`, nondeprecated fallback or omit the asset; never reuse a
   prior release's variant. Treat `READY` plus `deprecated: true` as
   existing-pin-only and exclude it from new selection.
5. Choose an appropriate published variant.
6. Use the variant's exact canonical `url`, which must be under
   `https://cdn.nlightlabs.com/objects/sha256/...` and agree with its
   `objectKey` and SHA-256.
7. Apply the asset according to the consuming page's own layout and
   accessibility behavior.

Do not construct a derivative URL relative to GitHub, jsDelivr, a Git tag, or a
repository checkout. Derivative bytes are not stored in Git.

Example page/theme reference:

```json
{
  "heroOrnament": "science-microscope-01"
}
```

The page does not need to know the vendor archive, original master filename,
private source path, R2 account, or object-upload machinery.

## Frozen legacy discovery

`manifests/index.json` and its referenced root asset, collection, and theme
manifests remain the frozen legacy discovery contract for already-existing
consumers. New V1 integrations must use the reviewed release pointer and
consumer catalog above. Updating or retiring the legacy path requires a
separate reviewed consumer-cutover contract and recovery proof.

## Variant selection

Consumers should prefer formats according to page requirements rather than
assuming one universal format.

- Prefer SVG for suitable vector illustrations/icons when safely publishable.
- Prefer WebP for raster artwork and photographs.
- Use PNG when transparency/compatibility or a specific source requirement
  makes it appropriate.
- Do not request private master formats.

## Accessibility

The consumer catalog exposes an accessibility role for each published logical
asset.

- `decorative`: consuming markup should normally use empty alternative text or
  presentation semantics as appropriate.
- `informative`: consuming markup should use the published `alt` value unless
  the page has a more context-specific accessible description.

A consuming page remains responsible for final semantic correctness in
context.

## Failure behavior

A production consumer should fail gracefully if:

- no reviewed current pointer has been selected;
- the pinned pointer or catalog cannot be loaded or hash-verified;
- a requested asset ID is absent;
- a requested variant is unavailable;
- a variant URL/key/hash relationship is invalid;
- a new selection resolves only to a deprecated asset.
- an asset is marked `UNAVAILABLE` (its variants must be empty).

Omit optional decoration or use an application-owned reviewed fallback rather
than breaking the entire page. Never fall back to a private path or an
unversioned repository-relative byte URL.

## Cache and dependency behavior

Production consumers pin the runtime release and each used `assetVersion` as
part of their own page or renderer release contract. Content-addressed CDN URLs
are immutable and may be cached aggressively. A library update is an
intentional dependency update, not an invisible mutation underneath a
classroom page.

A later current-pointer change or `UNAVAILABLE` tombstone does not revoke an
older commit-pinned catalog and cannot make an already published immutable CDN
URL disappear. If rights, privacy, safety, legal, or integrity authority
withdraws an old pin, the consumer must freeze use, build and review a new
dependency release that omits or replaces the asset, and deliberately cut over
to it. The owning incident process separately assesses and, only with explicit
authorization, quarantines or purges the affected CDN/R2 object and coordinates
cache invalidation. Consumers must not claim that following the newest pointer
alone protects historical pins.
