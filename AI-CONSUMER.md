# Northern Lights Asset Library — AI Consumer Guide

This repository is the public semantic/control layer for the Northern Lights Asset Library.

Runtime binary assets are delivered from:

https://cdn.nlightlabs.com/

## Discovery entry point

Start here:

`manifests/discovery/index.json`

Do not begin by loading the complete `manifests/assets.json` registry unless performing system administration or validation.

## Discovery workflow

1. Read `manifests/discovery/index.json`.
2. Choose the most relevant theme or collection.
3. For Photo Album work, prefer a theme shard when an appropriate theme exists.
4. For general page/post/exhibit work, choose one or more semantic collections.
5. Collection results are paged. Fetch only the pages needed.
6. Select assets using their actual metadata, not inferred filenames alone.
7. Use the supplied `preferredVariant.url` when appropriate.
8. Other public runtime formats are listed in `availableFormats`.

## Legacy discovery selection policy

The frozen legacy discovery layer contains only assets satisfying BOTH:

- `runtimeStatus = READY`
- `automaticSelection = ELIGIBLE`

Assets classified `EXCLUDE_AUTO`, `REVIEW`, `DERIVATIVE_NEEDED`, withheld, or otherwise unavailable are deliberately absent from automatic discovery.

This is a technical and curation filter, not durable rights approval. Legacy
discovery inclusion alone never authorizes use. Use still requires an
independently authorized Northern Lights Labs project context, and the reusable
library or its assets must not be redistributed as a standalone product.

## Stable identity

The asset `id` is the stable RuntimeId.

Use it when recording selections, recipes, references, or future state.

Do not treat filenames, vendor pack names, source paths, or derivative URLs as permanent identity.

## Photo Album theme contract

Every Photo Album theme uses these eight slots:

- `banner`
- `top-trim`
- `bottom-trim`
- `photo-frame`
- `corner-accent`
- `background`
- `divider`
- `decorations`

Theme shards live under:

`manifests/discovery/themes/`

Their slot assignments are curated recipe candidates and should be preferred over broad semantic collection searching when building that theme.

## Collections

Collection shards live under:

`manifests/discovery/collections/<collection-id>/`

Each page contains no more than 100 automatically eligible runtime assets.

Broad collections are candidate pools, not instructions to use every asset they contain.

Choose according to the requested subject, visual style, use case, age/context appropriateness, and composition.

## Public versus private data

This legacy discovery layer exposes selected runtime metadata and public
derivative URLs. Its presence is delivery evidence, not current rights evidence.
An authorized V1 consumer release is the durable public approval boundary.

Never request, infer, reconstruct, or expose:

- private library root locations
- RawAssets
- vendor/source ZIP organization
- private masters
- Blender source masters
- AI/EPS/FIG source files
- local filesystem paths
- R2 credentials
- management credentials

## Runtime delivery

Use the CDN URLs supplied by discovery metadata.

Do not invent CDN paths.

Do not substitute GitHub for runtime binary delivery.

GitHub is the versioned semantic/control layer.
Cloudflare R2 through `cdn.nlightlabs.com` is the runtime binary layer.
