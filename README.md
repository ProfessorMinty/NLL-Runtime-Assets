# Northern Lights Labs Runtime Assets

Public runtime asset repository for **Northern Lights Labs** applications.

`NLL-Runtime-Assets` is the delivery layer between the private **Northern Lights Asset Library** and applications that consume reusable visual assets.

It is designed to hold reviewed machine-readable manifests and public runtime
contracts exported by **NL Asset Control**. Approved browser-safe derivative
bytes live in Cloudflare R2 and are delivered through `cdn.nlightlabs.com`; they
are deliberately not stored in this Git repository.

## Purpose

Potential consumers include:

- Hughes Room Views
- Classroom Explorations
- Photo Album
- Northern Lights Labs web applications
- future Northern Lights Labs projects

Applications should reference **stable asset IDs** from generated manifests rather than depending on private source paths, vendor package layouts, or acquisition filenames.

The next release format adds immutable `assetVersion` identities and content-addressed `objectKey` values while retaining frozen legacy paths. See [`docs/IMMUTABLE_IDENTITY_CONTRACT.md`](docs/IMMUTABLE_IDENTITY_CONTRACT.md). The schemas are additive contract authority only; the current release pointer is unchanged until a later reviewed cutover.

Permanent release safeguards now define separate immutable-artifact and
pointer-only review lanes, plus the narrow browser-safe
`NLAssetConsumerCatalogV1` contract. No release or current pointer exists
merely because these contracts exist. See
[`docs/PUBLISHING-CONTRACT.md`](docs/PUBLISHING-CONTRACT.md).

## Repository boundary

This repository MAY contain:

- public asset manifests;
- stable runtime asset IDs;
- collections and theme recipes;
- accessibility metadata;
- integrity metadata such as SHA-256 hashes;
- limited public provenance needed for runtime or attribution;
- schemas and documentation for the runtime contract.
- the exact hash-reviewed V1 CI wheelhouse required to validate historical
  releases without contacting a mutable package index.

The only permitted entry under `assets/` is the tracked `.gitkeep` directory
sentinel. Runtime binaries and Git LFS pointers are rejected by the public
boundary validator. R2 is the sole authority for published derivative bytes;
reviewed, commit-pinned Git manifests are the semantic authority that identifies
those immutable objects.

The binary files under `ci/wheelhouse/` are a narrow validation-toolchain
exception, not runtime assets. Their filenames, sizes, SHA-256 identities, and
complete set are locked by the public boundary and V1 authority.

This repository MUST NOT contain:

- original vendor ZIP archives;
- private licensed master files;
- AI, EPS, PSD, BLEND, FBX, C4D, or any other source/master files;
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

Generated runtime manifests should not be manually edited when they can be reproduced by NL Asset Control.

Public CI validates manifest semantics and deterministic discovery without
placing runtime binaries in Git. The private publisher environment separately
validates every derivative byte. See
[`docs/VALIDATION_AND_DISCOVERY.md`](docs/VALIDATION_AND_DISCOVERY.md).

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
      "objectKey": "objects/sha256/5f/5fda50d42d908671b9e8dfb9eeebc0af3a7a7e311fdafb8996ae2a799beb54f9.svg",
      "url": "https://cdn.nlightlabs.com/objects/sha256/5f/5fda50d42d908671b9e8dfb9eeebc0af3a7a7e311fdafb8996ae2a799beb54f9.svg",
      "mimeType": "image/svg+xml"
    },
    {
      "format": "webp",
      "objectKey": "objects/sha256/a1/a111111111111111111111111111111111111111111111111111111111111111.webp",
      "url": "https://cdn.nlightlabs.com/objects/sha256/a1/a111111111111111111111111111111111111111111111111111111111111111.webp",
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
├── assets/.gitkeep         # directory sentinel; no runtime bytes in Git
├── manifests/
│   ├── index.json           # stable manifest entry point
│   ├── assets.json          # public runtime asset registry
│   ├── collections.json     # reusable asset collections
│   ├── themes.json          # theme/recipe references
│   └── releases/            # reviewed immutable catalogs and current pointer
├── schemas/                 # machine-readable runtime contracts
├── ci/wheelhouse/           # immutable offline V1 validation dependencies
├── docs/                    # publishing and integration documentation
├── RIGHTS.md                # repository rights boundary
└── README.md
```

The structure may evolve as NL Asset Control's publishing pipeline is implemented, but the private/public boundary and stable-ID contract should remain intact.

## Publishing pipeline

The intended pipeline is:

```text
Private Northern Lights Asset Library
        ↓
Curate / classify
        ↓
Approve for runtime use
        ↓
Validate rights + metadata
        ↓
Build browser-safe derivatives
        ↓
Upload immutable content-addressed objects to R2
        ↓
Generate deterministic manifests
        ↓
Review / merge manifests in NLL-Runtime-Assets
        ↓
Applications resolve stable IDs through Git manifests and fetch bytes from CDN
```

A normal publish should be repeatable. Re-running the exporter with unchanged inputs should produce equivalent runtime output rather than hand-edited drift.

## Manifest entry points

Existing legacy consumers still begin with the frozen compatibility entry:

```text
manifests/index.json
```

New V1 consumers use the reviewed pointer at
`manifests/releases/current.json`, then pin and hash-verify its
commit-addressed `consumer-catalog.json`. The pointer is intentionally absent
until an authorized first selection. Derivative bytes are always loaded from
the catalog's exact `cdn.nlightlabs.com` variant URLs. See
[`docs/EDUBLOGS-CONSUMER.md`](docs/EDUBLOGS-CONSUMER.md).

## Rights and licensing

**Public availability does not create a blanket license for reuse.**

Assets cataloged by this repository may originate from multiple sources with
different licensing terms. A `READY` asset in a reviewed V1 consumer-catalog
release means Northern Lights Labs approved only its exact listed runtime
variants for the intended public delivery context; an `UNAVAILABLE` tombstone
is identity/retirement evidence, not approval. Mere presence in the frozen
legacy manifests does not establish approval. Approval does not imply that
source masters, vendor packages, or underlying third-party rights are
transferred to repository visitors.

See [`RIGHTS.md`](RIGHTS.md) for the repository-wide rights boundary.

## Consumer rule

Consumers should treat the generated manifests as the API.

Do not couple application code to:

- local private-library-root paths;
- vendor ZIP names;
- extracted source directory structures;
- private acquisition metadata;
- human-maintained one-off URLs when a stable runtime ID exists.

The goal is simple: **NL Asset Control knows where an asset came from. Applications only need to know what the asset is.**

## Publisher operational certification

The permanent NL Asset Runtime Publisher uses reviewed, normal-merge pull requests.
Its provider identity is certified separately from asset publication. This documentation-only
checkpoint publishes no assets, creates no release tag, and changes no current pointer.
Derivative bytes remain in R2; private rights, candidate validation and recovery remain
the responsibility of NL Asset Control's transactional publisher.
