# Contributing

`NLL-Runtime-Assets` is primarily a **generated runtime repository**.

## Preferred contribution path

Changes to published asset metadata, collections, themes, and release catalogs
should normally originate in **NL Asset Control** and be regenerated into this
repository. Approved derivative bytes are uploaded separately to immutable R2
object keys and never enter Git.

Do not manually patch generated manifests to make a consumer work around bad source state. Fix the source state or exporter instead.

## Safe manual changes

Manual edits are appropriate for repository infrastructure such as:

- documentation;
- JSON schemas;
- validation tooling;
- CI workflows;
- publishing/integration contracts.

## Generated areas

The following paths are exporter-owned:

```text
manifests/
```

Treat direct edits there as exceptional recovery work only. Under `assets/`,
only `assets/.gitkeep` is permitted as a directory sentinel; the public-boundary
gate rejects all runtime bytes and Git LFS pointers.

## Pull-request expectations

A change that affects the runtime contract should explain:

- what changed;
- whether the schema version changes;
- whether existing consumers remain compatible;
- whether stable asset IDs are affected;
- how the change was validated.

All manifest and derivative-metadata changes must pass the repository runtime
validator. The private publisher separately validates and uploads the exact
derivative bytes to R2 before it proposes their manifests.

## Reviewed release lanes

Publication paths have narrower rules than ordinary infrastructure changes:

- `publish/artifacts/runtime-v1-YYYY.MM.DD.N/from/<source|none>/<operation-id>` may
  add only the matching immutable `release.json` and `consumer-catalog.json`
  directory. Its 64-character operation ID binds the exact base and artifact
  bytes, so a changed base or repaired candidate uses a new creation-only ref.
  It cannot modify an existing release or purpose ref.
- `publish/pointer/<select|rollback|restore>/<target>/from/<source|none>/<operation-id>`
  may add or modify only `manifests/releases/current.json`. The 64-character
  operation ID binds the exact reviewed base commit, operation, source, target,
  and canonical pointer bytes. A retry on the same base is stable, while a
  later rollback after restoration receives a new identity instead of
  colliding.
- other branches cannot change any `manifests/**` path. The legacy root and
  generated discovery remain frozen until a separately reviewed cutover lane
  with its own recovery proof is established.
- once the reviewed `release-policy.yml` activation marker is present on the
  base branch, changes to
  `.github/workflows/release-policy.yml`,
  `.github/workflows/validate-runtime.yml`,
  `tools/validate_public_boundary.py`, or
  `tools/validate_runtime_release.py` require a one-commit
  `infrastructure/runtime-v1-execution/<operation-id>` branch and a separately
  verified private `runtime-v1-execution-migration` receipt. Ordinary pull
  requests cannot change this exact four-path execution closure after the lock.
  The migration receipt supports a proved zero-accepted-tag state, so a defect
  found after safeguard activation but before the first release still has a
  fail-closed repair lane. V1 schemas, the retained V1 semantic validator,
  `requirements-ci.txt`, `tools/verify_v1_wheelhouse.py`, `.gitattributes`, and
  every exact file under `ci/wheelhouse/` are immutable in place at activation;
  future versions receive separate dependency and checkout contracts.

Do not merge that activation marker until the final owner/repository URL is
settled and the three permanent V1 schema `$id` values already name that exact
authority. The branch may be prepared for review, but activation stops while
ownership topology is unresolved. A marker merged under the current URL locks
that URL for V1; a later transfer cannot repair it in place or depend on a
redirect and instead requires direct permanent resolution or a new contract
version.

Activation also requires either an eligible GitHub Enterprise Cloud
organization with the native required-workflow rule (GitHub Team is not
eligible for that feature), or a separately designed dedicated independent
GitHub App evaluator. A same-name GitHub Actions check or context is spoofable
and cannot replace either enforcement path. Windows validation and recovery
should use a short checkout root plus Git long-path support where required; the
public gate's 255-character limit is per ASCII path component, not a fixed
total-path guarantee.

Every pull-request head must come from this repository. Fork-based pull requests
are unsupported because immutable V1 validation must audit the authoritative
repository's complete tag namespace, never fork-controlled or stale tag refs.
The trusted-base policy still treats the exact same-repository candidate head
only as data and never executes candidate code.

The `validate` check independently verifies the Git diff, strict schemas,
canonical JSON, predecessor graph, chronology, catalog/version/object hashes,
commit ancestry, annotated tag, and pointer/tag agreement. `validate`, the
trusted-base `release-policy`, and the independently credentialed
`runtime-rights-eligibility` check must all pass for the exact current PR
presentation. Do not combine repository infrastructure, artifacts, and pointer
selection in one pull request.
