# Runtime validation and discovery authority

The public repository stores runtime manifests and generated discovery JSON, but deliberately excludes derivative binaries. Validation therefore has two distinct gates.

## Public semantic gate

GitHub Actions runs only checks that a clean checkout can prove without Cloudflare credentials or derivative payloads:

```text
python -P tools/validate_runtime_release.py --repository
python -P tools/validate_public_boundary.py --revision HEAD
python tools/validate_identity_contracts.py
python tools/validate_runtime_semantics.py
python tools/generate_discovery.py --check
python tools/validate_discovery.py
python -m unittest discover -s tests -v
```

For a pull request, the retained V1 validator also runs `--pull-request` with
the exact base SHA, head SHA, and provider head ref. Runtime tag and repository
audits run through the trusted global dispatcher, which exhaustively classifies
all tag names and currently recognizes only exact V1 release IDs before routing
V1 semantics to the retained validator. The hourly schedule runs that global
repository audit and the safe-path public-boundary audit; mutable legacy tools
and tests are limited to ordinary pull-request and `main` push checks and cannot
deadlock or redefine historical tag acceptance.

The gate validates schemas, stable IDs, manifest references, deterministic ordering, discovery exact-set equality, preferred derivative URL/hash/version consistency, eight-slot theme shape, reviewed release path lanes, commit/tag/pointer/hash agreement when releases exist, and the absence of private/internal asset fields. It never treats missing Git-ignored binaries as a public-repository defect.

Pull-request validation uses full Git history and tags. Artifact changes must be
one commit adding new files in one matching immutable release directory, with a
branch identity bound to source, exact base, and exact artifact bytes;
pointer changes must be a one-commit pointer-only change and carry
collision-proof base/source/target/operation identity. Tag validation requires
a direct annotated purpose tag at the exact normal merge that introduced the
release. Infrastructure-only state remains valid with no
release, tag, or current pointer. Any future release catalog must pass the
public `NLAssetConsumerCatalogV1` schema and exactly match the release's
content-addressed CDN object evidence.

The separate `release-policy` check runs from trusted base through
`pull_request_target` with read-only permissions. It rejects every fork head so
the candidate checkout retains the authoritative repository's complete tag
namespace. It never runs candidate code. Immediately after materialization it
runs the standard-library-only public-boundary validator from trusted base, rejecting
nonregular modes and unapproved paths before dependency work. It then invokes
the standard-library-only `verify_v1_wheelhouse.py` and installs only the exact
hash-reviewed wheels with `--no-index`, `--require-hashes`, and `--no-deps`.
After installation, the trusted V1 pull-request lane uses the reviewed-base
schema copies to prove that every immutable candidate schema path has identical
bytes before repository mode runs. Only then does the trusted global dispatcher
evaluate the candidate-tree schema copies while routing repository semantics to
retained V1 authority. Every trusted command uses Python safe-path mode, and the
dispatcher loads its exact trusted sibling without adding candidate paths to
`sys.path`. It does not discover or execute trusted-base test
files, legacy validators, generator scripts, or candidate code.
It examines every new candidate commit tree and complete public
commit metadata/message in the exact `base..head` range. The public-boundary
gate permits only the exact root manifests, generator-owned discovery shapes,
reviewed release shapes, text/schema/documentation set, the exact two
workflows, the immutable hash-reviewed CI wheelhouse, and `assets/.gitkeep`.
It rejects unknown workflows or manifests, workflow write authority,
unreviewed triggers/actions/jobs/commands, Git-hosted runtime objects,
Git LFS pointers and filters, binary/private/master formats, oversized files,
absolute/private paths, and credential-shaped data. All `manifests/**` paths
remain frozen to ordinary branches until a separately reviewed legacy cutover
lane exists.

On Windows validation or recovery hosts, use a short checkout root and enable
Git long-path support where required. The public-boundary gate accepts only
ASCII tracked paths and limits each path component to 255 characters. It does
not claim one fixed total-path limit: that effective limit also depends on the
Windows, Git, and process configuration used for the checkout.

Both workflows use the exact x86-64-compatible
`python:3.12.11-bookworm` OCI index digest
`sha256:13c9584604a99ca134c4f41800f74ffc64ee6ac8cf555cf1e704a6087fc84f12`
and install with `--no-index` from `ci/wheelhouse/`. The public boundary verifies
the same wheel filenames, sizes, and SHA-256 values again as later
defense-in-depth; `verify_v1_wheelhouse.py` is the pre-install verifier. Provider
activation remains blocked until that immutable OCI image is retained under an
NLL-controlled mirror with recovery evidence, or an explicitly approved
provider-loss incident migration is certified; Docker Hub integrity by digest
does not guarantee permanent availability.

The V1 activation marker is also blocked until the final owner/repository
authority is settled and all three permanent schema `$id` values already name
it. The native required-workflow resolution requires an eligible GitHub
Enterprise Cloud organization, not GitHub Team. The alternative is a dedicated,
independently credentialed GitHub App evaluator; a same-name GitHub Actions
check or context is spoofable and cannot substitute for it. See GitHub's
[Enterprise Cloud ruleset workflow guidance](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-workflows-to-pass-before-merging).

`manifests/assets.json` is the authoritative input only for the frozen legacy
discovery generator. `READY` plus `ELIGIBLE` is technical/curation eligibility,
not durable rights approval. New consumers use an authorized V1 pointer and
consumer catalog. `tools/generate_discovery.py` is the sole legacy discovery
generator. Its `--check` mode builds into an isolated temporary directory and
byte-compares the complete generated tree, including stale or missing shards.

Theme manifests are suggestion recipes, not proof of a completed production theme pack. Discovery records every required slot and marks a recipe `COMPLETE` only when all eight filtered slots contain an eligible asset; otherwise it records `INCOMPLETE` and the exact `missingSlots`.

## Private byte-integrity gate

The publisher environment, where approved derivatives are present, runs:

```text
python tools/validate_runtime.py
```

That command runs the legacy runtime semantic validator with local derivative
verification enabled: it proves each referenced local derivative exists and
matches its declared byte count and SHA-256. It does **not** run the identity,
public-boundary, reviewed-release, deterministic-discovery, or regression-test
commands listed in the public semantic gate above.

A publication candidate must pass the complete public semantic suite and the
private byte-integrity command; neither substitutes for the other. The private
transactional publisher additionally streams and verifies the exact remote R2
bytes, enforces the format-specific and 8 GiB aggregate delivery limits, and
requires a versioned byte-content safety receipt for every `READY` object.
SVG and GLTF/GLB remain ineligible until their active-content/self-contained
validators are implemented and certified. Authorization and transaction
recovery receipts do not replace the fresh private eligibility gate required
for each exact purpose-PR presentation. This gate is not run in public CI and
does not place derivative binaries in Git.
