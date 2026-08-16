# Northern Lights Labs Runtime Assets

Public runtime asset repository for **Northern Lights Labs** applications.

`NLL-Runtime-Assets` is the delivery layer between the private **Northern Lights Asset Library** and applications that consume reusable visual assets.

It is designed to hold curated, browser-safe derivatives and machine-readable manifests exported by **NL Asset Control**.

## Purpose

Potential consumers include:

- Hughes Room Views
- Classroom Explorations
- Photo Album
- Northern Lights Labs web applications
- future Northern Lights Labs projects

Applications should reference **stable asset IDs** from generated manifests rather than depending on private source paths, vendor package layouts, or acquisition filenames.

## Repository boundary

This repository MAY contain:

- approved browser-safe image derivatives;
- SVG assets approved for public delivery;
- WebP and PNG derivatives;
- public asset manifests;
- stable runtime asset IDs;
- collections and theme recipes;
- accessibility metadata;
- integrity metadata such as SHA-256 hashes;
- limited public provenance needed for runtime or attribution;
- schemas and documentation for the runtime contract.

This repository MUST NOT contain:

- original vendor ZIP archives;
- private licensed master files;
- AI, EPS, PSD, BLEND, FBX, C4D, or similar source masters unless explicitly approved for public distribution;
- purchase receipts;
- private license documents;
- credentials or secrets;
- private classroom information;
- private photographs;
- internal curation notes;
- unreleased or restricted project assets.

## Source of truth

The canonical asset library is maintained privately through **NL Asset Control**.

The private library owns acquisitions, source masters, provenance, curation metadata, logical-asset grouping, human overrides, and publishing eligibility.

This repository is a **generated publishing target**, not the canonical vault.

Generated runtime files should not be manually edited when they can be reproduced by NL Asset Control.

## Runtime model

A published asset has a stable identity independent of its physical filename or source package.

Conceptually:

```json
{
  "id": "science-microscope-01",
  "name": "Microscope",
  "type": "illustration",
  "tags": ["science", "education"],
  "accessibility": {
    "role": "decorative"
  },
  "variants": [
    {
      "format": "svg",
      "path": "assets/science/science-microscope-01.svg",
      "mimeType": "image/svg+xml"
    },
    {
      "format": "webp",
      "path": "assets/science/science-microscope-01.webp",
      "mimeType": "image/webp"
    }
  ]
}
```

Consuming applications should reference:

```text
science-microscope-01
```

rather than private source paths, vendor filenames, or archive names.

## Initial structure

```text
/
├── assets/                  # generated browser-safe derivatives
├── manifests/
│   ├── index.json           # stable manifest entry point
│   ├── assets.json          # public runtime asset registry
│   ├── collections.json     # reusable asset collections
│   └── themes.json          # theme/recipe references
├── schemas/                 # machine-readable runtime contracts
├── docs/                    # publishing and integration documentation
├── RIGHTS.md                # repository rights boundary
└── README.md
```

The structure may evolve as NL Asset Control's publishing pipeline is implemented, but the private/public boundary and stable-ID contract should remain intact.

## Publishing pipeline

The intended pipeline is:

```text
Private NL Asset Library
        ↓
Curate / classify
        ↓
Approve for runtime use
        ↓
Validate rights + metadata
        ↓
Build browser-safe derivatives
        ↓
Generate deterministic manifests
        ↓
Stage / publish to NLL-Runtime-Assets
        ↓
Applications consume stable asset IDs
```

A normal publish should be repeatable. Re-running the exporter with unchanged inputs should produce equivalent runtime output rather than hand-edited drift.

## Manifest entry point

Consumers should begin with:

```text
manifests/index.json
```

That file points to the current asset, collection, and theme manifests. This gives consumers one stable discovery location while allowing the internal runtime contract to evolve deliberately.

## Rights and licensing

**Public availability does not create a blanket license for reuse.**

Assets in this repository may originate from multiple sources with different licensing terms. Inclusion means Northern Lights Labs has approved that specific runtime derivative for its intended public delivery context. It does not imply that source masters, vendor packages, or underlying third-party rights are transferred to repository visitors.

See [`RIGHTS.md`](RIGHTS.md) for the repository-wide rights boundary.

## Consumer rule

Consumers should treat the generated manifests as the API.

Do not couple application code to:

- local `E:\Assets` paths;
- vendor ZIP names;
- extracted source directory structures;
- private acquisition metadata;
- human-maintained one-off URLs when a stable runtime ID exists.

The goal is simple: **NL Asset Control knows where an asset came from. Applications only need to know what the asset is.**
