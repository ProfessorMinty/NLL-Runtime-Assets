# Rights and Licensing Boundary

This repository is a **public runtime delivery repository**, not a blanket asset license.

## What public visibility means

A `READY` asset in a reviewed V1 consumer-catalog release means Northern Lights
Labs approved only its exact listed runtime variants for the intended public
delivery context. An `UNAVAILABLE` tombstone is stable-identity and retirement
evidence, not derivative approval or delivery permission. Mere presence in the
frozen legacy manifests is not durable approval evidence; legacy records may
carry the fail-closed `private-library` state and must still satisfy current
publication eligibility before entering a V1 release.

It does **not** automatically mean that:

- repository visitors receive ownership of the asset;
- source/master files are redistributable;
- vendor license rights transfer to third parties;
- an asset may be resold, repackaged, sublicensed, or redistributed independently;
- every asset in the repository shares the same licensing terms;
- public visibility overrides the original creator or vendor license.

## Private licensing records

Detailed acquisition and licensing records belong in the private Northern Lights Asset Library and associated private documentation.

Do not publish private receipts, license keys, purchase records, vendor archives, or master source packages here merely to prove provenance.

## Runtime manifest rights status

The frozen legacy asset registry uses exactly:

- `approved-runtime-use`
- `credit-required`
- `private-library`

`private-library` is a fail-closed legacy state and is not publication approval.
The V2 registry accepts only `approved-runtime-use` and `credit-required` for
exported records. `restricted` is not a valid status in either machine
contract.

The narrow V1 consumer catalog does not expose a competing rights-status field.
A `READY` record and every delivered variant must have passed current private
publication eligibility. An `UNAVAILABLE` record is a non-deliverable stable-ID
tombstone: it has no variants, but every retained browser-visible field must
still pass current permission, privacy, sanitization, and minimization review.
Public credit and sanitized provenance appear only where permitted and needed.
Detailed rights evidence and policy decisions remain in the private authority.

These machine states help Northern Lights Labs applications decide whether and
how an asset may be delivered. They do not replace the underlying private
license record.

## Attribution

When an asset requires public attribution, the runtime record should include the exact approved credit text or attribution reference needed by consuming applications.

## Default rule

If rights are uncertain, the asset should **not be published** by NL Asset Control.

Uncertainty belongs in the private review queue, not in the public runtime repository.
