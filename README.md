# NLL-Runtime-Assets
Public runtime asset registry and web-safe derivatives for Northern Lights Labs applications.

# Northern Lights Labs Runtime Assets

Public runtime asset repository for Northern Lights Labs applications.

This repository contains curated, web-safe visual assets and machine-readable manifests exported from the private Northern Lights Asset Library.

## Purpose

`NLL-Runtime-Assets` is the public delivery layer between the private Northern Lights asset library and applications that consume reusable visual assets.

Potential consumers include:

- Hughes Room Views
- Classroom Explorations
- Photo Album
- Northern Lights Labs web applications
- future Northern Lights Labs projects

Applications should reference stable asset IDs and generated manifests rather than depending on private source files or vendor package structures.

## Repository Boundary

This repository MAY contain:

- approved browser-safe image derivatives;
- SVG assets approved for public delivery;
- WebP and PNG derivatives;
- public asset manifests;
- stable runtime asset IDs;
- collections and theme recipes;
- accessibility metadata;
- limited public provenance information;
- generated indexes required by consuming applications.

This repository MUST NOT contain:

- original vendor ZIP archives;
- private licensed master files;
- AI, EPS, PSD, BLEND, FBX, C4D, or other source masters unless explicitly approved for public distribution;
- purchase receipts;
- license documents intended for private recordkeeping;
- credentials or secrets;
- private classroom information;
- private photographs;
- internal curation notes;
- unreleased or restricted project assets.

## Source of Truth

The canonical asset library is maintained locally through **NL Asset Control**.

The private library contains acquisitions, source masters, provenance, curation metadata, logical-asset groupings, and other authoring information.

This repository is a **generated publishing target**, not the canonical asset vault.

Generated runtime files should not be manually edited when they can be reproduced by NL Asset Control.

## Runtime Model

A public runtime asset should have a stable identity independent of its physical filename.

Example:

```json
{
  "id": "science-microscope-01",
  "name": "Microscope",
  "type": "illustration",
  "themes": ["science", "education"],
  "variants": {
    "svg": "assets/science/science-microscope-01.svg",
    "webp": "assets/science/science-microscope-01.webp"
  }
}
