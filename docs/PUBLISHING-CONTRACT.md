# Publishing Contract

This document defines the boundary between the private Northern Lights Asset Library and `NLL-Runtime-Assets`.

## 1. Authority

**NL Asset Control is the authoring authority.**

`NLL-Runtime-Assets` is a generated public delivery target.

The repository should never become the place where private masters, acquisition state, or licensing evidence are curated by hand.

## 2. Stable runtime identity

Every published logical asset receives a stable public ID.

Example:

```text
science-microscope-01
```

The ID belongs to the logical asset, not to a particular filename, resolution, vendor path, or source archive.

### ID rules

- IDs are lowercase kebab-case.
- IDs must be unique within the public registry.
- Once published, an ID must not be silently reassigned to a different logical asset.
- Replacing a derivative does not require changing the logical asset ID.
- If an asset is retired, preserve its identity and mark it deprecated rather than reusing the ID for unrelated content.

## 3. Publish eligibility

NL Asset Control should refuse publication unless the logical asset passes the configured publishing checks.

At minimum, a publishable asset should have:

- a stable public ID;
- an approved runtime-use rights state;
- at least one browser-safe derivative;
- an accessibility role;
- valid runtime metadata;
- no blocking validation errors.

If an informative asset is published, an appropriate alt description must be present.

If public credit is required, the exact approved credit text must be present.

## 4. Public derivatives

Only derivatives intentionally approved for browser/runtime delivery belong here.

Typical runtime formats include:

- SVG
- WebP
- PNG when required

Private source/master formats remain outside the repository unless separately and explicitly approved for public distribution.

Each published derivative should carry enough integrity metadata for deterministic validation, including:

- relative runtime path;
- MIME type;
- byte size;
- SHA-256 hash;
- raster width/height when applicable.

## 5. Deterministic generation

Generated manifests should be deterministic.

Given equivalent source state and exporter version, repeated generation should produce equivalent semantic output.

Recommended practices:

- stable sorting by asset ID;
- normalized path separators using `/`;
- consistent JSON formatting;
- explicit schema versioning;
- no machine-specific absolute paths;
- no volatile timestamps inside individual asset records.

A top-level generation timestamp is acceptable for publish tracking.

## 6. Manifest contract

Consumers discover runtime data through:

```text
manifests/index.json
```

That index points to:

- `assets.json`
- `collections.json`
- `themes.json`

Applications should treat these generated manifests as the public API.

## 7. Collections

Collections are reusable groups of stable asset IDs.

Examples might include:

- science props
- botanical linework
- museum ornaments
- ocean icons

Collections do not duplicate asset records. They reference IDs from the asset registry.

## 8. Themes

Themes are recipes, not copies of assets.

A theme may assign stable asset IDs to semantic slots such as:

```json
{
  "heroOrnament": "science-microscope-01",
  "cornerDecorations": [
    "science-beaker-01",
    "science-atom-01"
  ]
}
```

The consuming application remains responsible for layout, interaction, animation, and presentation behavior.

## 9. Failure behavior

Publishing should fail closed.

Do not partially publish an invalid asset set and then silently report success.

A future NL Asset Control exporter should:

1. validate candidate assets;
2. build derivatives into a staging location;
3. build manifests from staged output;
4. validate manifests and referenced files;
5. only then promote/stage the completed runtime package for repository publication.

## 10. Private data prohibition

Generated output must never expose:

- `E:\Assets` absolute paths;
- original ZIP names when not intentionally public;
- receipts;
- license keys;
- private license documents;
- internal review notes;
- private classroom/student information;
- credentials or secrets.

The runtime layer should know enough to serve an asset safely, not enough to reconstruct the private acquisition vault.
