# Edublogs Consumer Notes

This repository is intended to be consumable by Hughes Room Views and other browser runtimes without exposing private asset-library state.

## Stable discovery point

Consumers should begin with:

```text
manifests/index.json
```

The index tells the consumer where to find the asset registry, collections, and themes for that runtime package.

## Development vs production

During development, a consumer may temporarily read the current branch output.

For production Edublogs pages, prefer a **pinned immutable release/tag** rather than tracking `main` directly.

Conceptually:

```text
https://cdn.jsdelivr.net/gh/ProfessorMinty/NLL-Runtime-Assets@<release>/manifests/index.json
```

This prevents a newly published library revision from silently changing an already-deployed classroom page.

## Resolution flow

A consumer should resolve an asset in this order:

1. Load `manifests/index.json`.
2. Load the referenced asset registry.
3. Resolve a stable asset ID.
4. Choose an appropriate published variant.
5. Construct the runtime URL relative to the pinned repository/release base.
6. Apply the asset according to the consuming page's own layout and accessibility behavior.

Example page/theme reference:

```json
{
  "heroOrnament": "science-microscope-01"
}
```

The page does not need to know the vendor archive, original master filename, or private source path.

## Variant selection

Consumers should prefer formats according to page requirements rather than assuming one universal format.

Typical guidance:

- Prefer SVG for suitable vector illustrations/icons when safely publishable.
- Prefer WebP for raster artwork and photographs.
- Use PNG when transparency/compatibility or a specific source requirement makes it appropriate.
- Do not request private master formats.

## Accessibility

The runtime registry exposes an accessibility role for each published logical asset.

- `decorative`: consuming markup should normally use empty alternative text / presentation semantics as appropriate.
- `informative`: consuming markup should use the published `alt` value unless the page has a more context-specific accessible description.

A consuming page remains responsible for final semantic correctness in context.

## Failure behavior

A production consumer should fail gracefully if:

- the manifest cannot be loaded;
- a requested asset ID is absent;
- a requested variant is unavailable;
- an asset is marked deprecated.

Recommended behavior is to omit the optional decoration or use an application-owned fallback rather than breaking the entire page.

## Cache/version behavior

Production consumers should pin the asset release/version as part of the page or renderer release contract.

A library update should be an intentional dependency update, not an invisible mutation underneath a classroom page.
