# Publishing Contract

This document defines the boundary between the private Northern Lights Asset Library and `NLL-Runtime-Assets`.

## 1. Authority

**NL Asset Control is the authoring authority.**

`NLL-Runtime-Assets` is the generated public manifest and runtime-contract
authority. Cloudflare R2 is the sole store for approved derivative bytes, which
are delivered through `cdn.nlightlabs.com`.

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

Only derivatives intentionally approved for browser/runtime delivery may be
referenced by this repository's manifests. Their immutable content-addressed
bytes belong in R2, never in this Git repository. Git contains the reviewed
metadata that binds stable asset/version identities to exact R2 object keys,
CDN URLs, byte counts, and SHA-256 hashes.

Typical runtime formats include:

- SVG
- WebP
- PNG when required

All source/master files remain in the private authority. Even approved
browser-safe derivative bytes remain outside Git and are published only to R2.
The repository's `assets/.gitkeep` file is a directory sentinel, not a byte
publication lane; Git LFS is not an alternative lane.

Each published derivative should carry enough integrity metadata for deterministic validation, including:

- immutable content-addressed `objectKey`;
- canonical `https://cdn.nlightlabs.com/<objectKey>` URL;
- MIME type;
- byte size;
- SHA-256 hash;
- raster width/height when applicable.

A legacy relative path may remain only as explicitly labeled migration
metadata in a legacy contract. It is not V1 byte authority and must never be
used to infer a Git-hosted derivative.

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

## 6. Reviewed immutable releases

Runtime publication is a two-gate reviewed workflow. The publisher never
commits directly to `main`.

1. `publish/artifacts/<release-id>/from/<source-release-id-or-none>/<operation-id>`
   adds exactly:

   ```text
   manifests/releases/<release-id>/release.json
   manifests/releases/<release-id>/consumer-catalog.json
   ```

   The release directory is immutable after merge. The release descriptor
   records the predecessor, exact catalog hash and schema version, immutable
   CDN object evidence, precomputed source-candidate identity,
   `publicationAuthorizationIdentity`, and
   `transactionRecoveryAuthorizationIdentity`. The first authorization is the
   hash identity of the authenticated acceptance of this exact pre-publication
   preview. The second authorizes recovery of this publication transaction if
   it fails. Neither is a completed-publication receipt, and the recovery
   authorization is not standing permission for a future pointer rollback.
   Completed transition receipts remain private. The descriptor does not contain
   its own Git commit SHA or its completed staging-descriptor hash; either would
   be self-referential. Every publisher purpose branch contains exactly one
   commit on its reviewed base. The artifact operation ID is SHA-256 over the
   exact ordered UTF-8 material below; every line ends in LF:

   ```text
   runtime-artifact-operation-v1
   <release-id>
   <source-release-id-or-none>
   <exact-lowercase-40-hex-reviewed-base-commit>
   <sha256-of-exact-release.json-bytes>
   <sha256-of-exact-consumer-catalog.json-bytes>
   ```

   The fixed cross-language test vector is
   `50b553b2e9ba5d8a31cc0a2da56bdf3dfd82de35c89851123d7f5f5ba749b0d6`.
   Binding the reviewed base and exact artifacts makes retry refs collision-safe:
   if main or candidate bytes change, the publisher creates a new one-commit
   purpose ref rather than updating or deleting the prior ref.
2. After the artifact PR merges, the publisher constructs the annotated
   `runtime-v1-YYYY.MM.DD.N` tag object **without creating its ref**. It materializes
   the exact object in the reviewed checkout, proves its Git object SHA, and
   runs:

   ```text
   python -P tools/validate_runtime_release.py --tag-object <tag-object-sha> \
     --tag-name <release-id> --main <reviewed-main-sha>
   ```

   The reviewed global dispatcher first rejects any tag outside the currently
   recognized namespace, then delegates the exact V1 tag-object proof to the
   retained V1 authority.

   Before any tag-ref creation, the gateway also requires a current
   authenticated global scheduled-audit liveness receipt; stale, disabled, or
   unreachable monitoring stops before the immutable ref mutation. Preflight
   runs Git ref-format validation, audits every existing runtime-prefixed ref,
   and proves that neither the exact `refs/tags/<release-id>` name nor any
   descendant `refs/tags/<release-id>/...` already exists; a file/directory ref
   conflict therefore fails before mutation. The
   equivalent object created through the Git data API must return the same SHA.
   Only after pre-ref validation and that global liveness gate pass may the App atomically create
   `refs/tags/<release-id>` pointing to that already-validated object. The tag
   binds the exact normal two-parent release-introduction merge commit to a
   canonical pointer receipt. The direct tag-object target, type, and internal
   tag name must match; a later commit that merely still contains the files is
   invalid.
   Its tagger header must use the exact certified publisher identity
   `NL Asset Runtime Publisher <nl-asset-runtime-publisher[bot]@users.noreply.github.com>`
   in UTC, and the complete immutable tag object is rejected if any header or
   receipt contains private or credential-shaped text.
3. Ref creation is not acceptance. The publisher immediately rereads and
   verifies the exact tag ref and object, then waits for a later successful
   reviewed-default-branch `schedule` audit whose run started after ref creation
   and enumerated that exact flat or nested V1 ref. The private ledger must then
   record durable terminal `RELEASE_TAG_ACCEPTED` evidence through a
   `runtime-tag-acceptance-v1` receipt. No pointer branch may be created for an
   unaccepted target. This exact-target acceptance and fresh global monitor
   liveness gate also apply to later select, rollback, and restore operations.
4. A collision-proof branch named
   `publish/pointer/<select|rollback|restore>/<target>/from/<source|none>/<operation-id>`
   may then add or modify only `manifests/releases/current.json`. The operation
   ID is SHA-256 over the exact ordered UTF-8 material below. Every line,
   including the final pointer-hash line, ends in LF:

   ```text
   runtime-pointer-operation-v1
   <operation>
   <target-release-id>
   <source-release-id-or-none>
   <exact-lowercase-40-hex-reviewed-base-commit>
   <sha256-of-exact-canonical-pointer-bytes>
   ```

   The fixed rollback test vector produces
   `b59ee22125fd61e6efefb57ae96e56155b25a19abe9ae38262729ce957cc9fe7`.
   The pointer contains the already known
   release-artifact commit and exact catalog path/hash. Its merge is the
   semantic cutover. Select chooses
   the first root or a direct next release; rollback selects a strict ancestor;
   restore selects a strict descendant; source must equal the base pointer.

Before any artifact, select, rollback, or restore purpose PR is authorized, an
independently credentialed private policy service must verify the exact
candidate/staging identity and authenticated authorizations against the current
rights, privacy, safety, legal/takedown, quarantine, and R2 authorities. Every operation,
including a delayed first `select`, rechecks every target alias and object plus
remote R2 existence, bytes, hashes, keys, MIME/extension, and cache policy.
Every retained browser-visible field of an `UNAVAILABLE` tombstone also needs
current permission, privacy, sanitization, and minimization approval.

Rollback or restore additionally compares the target with current selection
state. It rejects revival of an asset now `UNAVAILABLE` or quarantined, and
rejects any transition from `READY` plus `deprecated: true` to a selectable
`deprecated: false` ancestor/descendant—including fallback targets—unless a
separate explicit reactivation authorization is bound into the private receipt.
For a content/object-level rights, privacy, safety, legal, or integrity block, the gate
tombstones every alias that references the blocked digest/object. A record- or
provenance-specific block may leave another alias `READY` only when private
authority explicitly proves that alias is independently permitted.

The durable private receipt binds the numeric repository identity, PR node and
number, exact head ref, reviewed base/head SHAs, operation, source/target,
catalog/artifact hashes, each exact private-authority revision, R2 checked-state
identity, decision time, and expiry. It exposes its human-readable target diff
only through the authenticated private service. GitHub receives only bounded
browser-safe status and an opaque receipt hash; check-run title, summary, text,
annotations, and linked public logs contain no private evidence.

The service reports the exact `runtime-rights-eligibility` check through an
independently credentialed GitHub integration with no contents-write authority;
the publisher never holds that credential. A purpose presentation first makes
the check pending and requires a fresh service evaluation. A non-purpose
not-applicable success is allowed only after proving that exact PR/ref is
neither a publisher-purpose lane nor the exact V1 execution-migration lane and
can never authorize the same head SHA later presented through either protected
ref shape. The execution-migration lane is always applicable: the same required
integration-bound `runtime-rights-eligibility` check validates its dedicated
migration receipt, exact base/head/ref, four-path closure, operation identity,
old/new execution evidence, and monitor recertification; it must never emit
not-applicable for that lane. Even a bounded not-applicable result validates and
binds public-safe PR/ref metadata; edits invalidate the result. At merge, the successful result and bound private receipt
must be no more than 15 minutes old, every bound authority revision must still
be current and reachable, and the exact PR presentation must be unchanged.
Relevant rights, safety, takedown, quarantine, R2, PR, or ref changes
automatically invalidate the prior decision and re-evaluate every affected open
purpose PR. Stale, unreachable, revoked, mismatched, or unevaluated state fails
closed even if GitHub still displays an older green conclusion. The gateway
validates this bound receipt, not merely a latest check name on the head SHA.
Invalidation immediately transitions the exact GitHub check to pending or
failure. The gateway is the exclusive routine merge initiator for every PR,
including ordinary infrastructure changes. It uses App ID `4791815` for
ordinary/artifact/pointer PRs and the separately certified workflow-capable App
only for the exact execution-migration lane. Immediately before merge it obtains
a short-lived, single-use lease over the current authority revisions,
revalidates the receipt or bounded not-applicable decision plus exact
PR/provider state, and consumes that lease in the merge transaction. It calls
the merge API with the fixed ASCII title `Merge reviewed pull request #<number>`
and message `Reviewed <head-sha> onto <base-sha>.`; mutable PR title/body or source
branch text never enters the commit. Human reviewers are approval-only and have
no routine contents or merge permission; a human merge is break glass.
Provider certification binds the repository's merge-message settings and must
prove a post-check revocation denies the merge request itself; a green display
during re-evaluation is never authority. Owner administration is break glass,
not a normal merge path.
The public validator proves topology, not current private permission, and raw
rights evidence never enters public Git.

Rollback and forward restoration are new reviewed pointer-only changes.
Accepted, validated release tags and merged release directories are never
moved, rewritten, or deleted. A rejected, never-accepted ref may be removed
only through the explicit owner-authorized break-glass procedure below.

The owning `NLAssetConsumerCatalogV1` schema contains only public stable IDs,
immutable versions and variants, display/search metadata, reviewed
accessibility/credit, readiness/deprecation/fallback state, bounded public
themes/subjects/styles/use-cases, and sanitized public provenance. It excludes
private paths, raw rights evidence, internal notes, credentials, source masters,
and any unowned competing update identity. Release validation recomputes every
public assetVersion and requires the catalog and descriptor to enumerate exactly
the same immutable CDN objects. Reused identical content-addressed objects may
serve multiple assets only when their full immutable variant evidence (format,
MIME, dimensions, byte count, hash, key, and URL) agrees; duplicate variants
within one asset are forbidden. One SHA-256 digest has exactly one canonical
runtime object key, format, MIME type, dimensions, byte count, and URL across
the entire release graph; polyglot or extension aliases are not a V1 feature.
Every successor catalog must retain every stable asset ID from its declared
predecessor. A still-deliverable retirement may remain `READY` with
`deprecated: true`. A rights-, privacy-, safety-, legal-, or integrity-blocked asset becomes an
`UNAVAILABLE` tombstone with `deprecated: true`, no variants, and therefore no
object contribution of its own. A shared immutable object remains in the
release descriptor only while another `READY` asset still references it. It may
identify a currently `READY`, nondeprecated fallback or explicitly have none.
Its new `assetVersion` binds that unavailable state. Omission is not deletion
and fails publication. `READY` plus `deprecated: true` is advisory: existing
pinned dependencies may continue to render it, but new selection must exclude
it.

Consumers of the current pointer must never reuse a prior variant for an
`UNAVAILABLE` asset. They may use its verified `READY`, nondeprecated fallback
or omit the asset. Immutable historical manifests remain evidence, not current permission.
If any rights, privacy, safety, legal, or integrity condition requires delivery
to cease, freeze publication and use a separate owner-authorized CDN/R2
quarantine or purge runbook with preserved evidence, complete shared-alias
analysis, and independently verified scope; routine publication and rollback
never delete immutable bytes. Historical commit-pinned manifests and old CDN
URLs may remain reachable until every consumer updates and separately
authorized object quarantine/purge completes, so a tombstone alone is not a
claim of immediate erasure.

Extension, MIME, hash, and size metadata do not prove active-content safety.
Every `READY` object must have a current private
`runtime-byte-safety-receipt-v1` bound to its SHA-256, exact bytes, media type,
validator name/version/hash, policy version, result, and validation time. SVG
validation rejects scripts, `foreignObject`, event handlers, external links,
CSS `@import`, and external `url(...)` loads. GLTF/GLB validation uses a reviewed
parser and requires a self-contained resource graph with no external URI.
These formats remain blocked from `READY` until their exact validator is
implemented, independently reviewed, and certified; metadata-only checks are
insufficient. The private eligibility receipt binds the complete byte-safety
receipt set without exposing its private details in public Git.

Release and catalog timestamps are identical canonical UTC `Z` values whose
date matches the release ID. Release IDs advance monotonically, every non-root
predecessor exists, and the immutable predecessor graph is one linear chain
with exactly one root and one tip. A new artifact release is blocked until the
reviewed current pointer selects the existing tip; this prevents concurrent
sibling releases and requires restoration to the tip before publishing a new
successor after rollback.

Release sequence numbers are permanently bounded to `Int32.MaxValue`, and
raster width and height use the same bound. A V1 SVG is at most 2 MiB; WebP,
PNG, JPG, or JPEG is at most 16 MiB; GLTF JSON is at most 8 MiB; and GLB is at
most 64 MiB. No release object exceeds 64 MiB, and the unique object set for one
release is at most 8 GiB. JSON artifacts separately remain at most 16 MiB.
Remote hash/size verification and publication stream bytes and never buffer the
full candidate payload. These are owning cross-language limits shared by the
schemas, Python gate, and .NET publisher, not implementation-dependent overflow
behavior. Byte count participates in immutable asset-version material and must
round-trip exactly.
The permanent browser `assetId` is 3-160 lowercase kebab-case characters,
matching the owning NL Asset Control V1 contract.
V1 contains at most 25,000 retained logical assets, at most seven variants per
asset, and at most 65,000 distinct release objects. These permanent V1 bounds
keep schema validation and browser consumption predictable under the 16 MiB
public JSON limit. Larger libraries require a new reviewed sharded contract,
not silent growth of V1.
All browser-visible catalog strings reject C0/C1 controls and Unicode
bidirectional-format controls. This prevents escaped control data and visual
direction spoofing from passing a text-only Git scan; normal Unicode and emoji
composition remain supported.

The reviewed `release-policy.yml` file is the V1 authority activation marker.
From the commit that first contains that marker, the three V1 release, pointer,
and consumer-catalog schemas, the retained V1 validator, the requirements and
wheelhouse verifier, the exact eight wheel files, and `.gitattributes` are
immutable in place. This lock applies even when no release tag exists; a changed
semantic contract must add a versioned schema, validator, and dependency lane
rather than reinterpreting V1. Pointer/tag validation also byte-compares the
locked authority to the release-artifact commit.

The activation marker **must not be merged to `main`** until the final owner,
repository name, and permanent V1 URL authority are settled. In particular,
the exact `$id` values in all three V1 schemas and every owner/repository raw
URL must already name the authority that V1 will keep. A safeguard branch may
be prepared and reviewed while this topology decision is pending, but marker
merge is an explicit stop. Merging it under the current `ProfessorMinty`
authority permanently preserves those exact V1 URLs; a later organization
transfer may not edit the locked schema IDs or rely on redirects. It must either
prove the original URLs continue to resolve directly as permanent authority or
introduce a separately reviewed new contract version. Resolve and recertify the
ownership topology before activation, not between activation and first release.

### GitHub enforcement

The permanent enforcement target below has a current provider/ownership gate.
GitHub's native `Require workflows to pass before merging` rule requires an
eligible GitHub Enterprise Cloud organization; a GitHub Team organization is
not sufficient. GitHub documents that rule in its
[Enterprise Cloud ruleset workflow guidance](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-workflows-to-pass-before-merging).
The verified owner of this repository is currently the personal User account
`ProfessorMinty`, so the exact trusted `.github/workflows/release-policy.yml`
workflow cannot presently be made a required workflow for this repository. A
same-name required status check or GitHub Actions context is spoofable by
candidate-controlled workflow/job naming and is not an acceptable substitute.

Therefore publisher mutation remains prohibited after this safeguard code is
merged. Do not create publisher purpose refs or release tags, and do not claim
the ruleset gate is certified, until either the repository is hosted under an
eligible organization ruleset or a different independently trusted,
unspoofable enforcement mechanism is researched and proven. This is a hosting
eligibility blocker, not permission to weaken the check. Rulesets that can be
prepared independently do not authorize publication by themselves.

There are two distinct acceptable resolution paths:

- **Path A — eligible Enterprise Cloud organization ownership.** Transfer or
  recreate the runtime repository under an eligible GitHub Enterprise Cloud
  organization that supports exact required workflows; GitHub Team does not
  satisfy this gate. Before the activation-marker merge, inventory, update, and
  recertify every owner/repository name, raw-content URI, schema `$id`, consumer
  reference, publisher target, and configuration value. Prove commit-pinned
  consumer URLs resolve directly at the new authority without relying on
  provider redirects. A transfer may preserve numeric repository identity only
  when live provider evidence proves it; recreation always has a new identity
  and history trust boundary. In either case recertify the numeric owner and
  repository IDs, App installation and repository selection, App permissions,
  workflow ID, ruleset IDs, default branch, and every live enforcement setting
  before mutation. Existing personal-account certification does not carry
  across either operation.
- **Path B — dedicated independent App evaluator.** Research, threat model,
  implement, and independently review a dedicated GitHub App evaluator that
  does not execute candidate-controlled policy and reports an exact
  integration-bound result. A same-name GitHub Actions check or context is
  spoofable and cannot substitute for that independent evaluator. Record a
  replacement enforcement contract, App identity/permission boundary, and exact
  configuration recipe; the Path A ruleset recipe below does not apply
  unchanged to that mechanism.

If Path A is selected, after the ownership gate is resolved and the merged-main
`validate` check passes, configure the following enforcement before granting
the publisher any mutation opportunity. `Protect runtime main`, which contains
the GitHub `workflows` rule, must be an organization/enterprise ruleset targeted
only to this exact runtime repository and must pin the exact source repository,
default-branch ref, and workflow path. Remaining ref rules may be repository
rulesets when supported. GitHub's organization-ruleset read endpoint requires
organization Administration **write**, and it withholds bypass actors without
write access. The gateway must therefore certify the inherited organization
ruleset through a separate narrowly scoped organization-Administration-write
identity that is independently controlled, rotated, and used operationally only
for read/evidence calls. Repository-rule evidence uses the least privilege that
returns complete bypass data. The contents-writing publisher App must not gain
Administration permission, and a broad operator token is not an acceptable
substitute.

- `Protect runtime main`, targeting `~DEFAULT_BRANCH`, with no bypass actors:
  block deletion and force pushes; require a pull request using normal merge
  commits, one approving review, stale-review dismissal, approval after the
  latest push, resolved review threads, and branches strictly up to date with
  the actual target before merge so all three trusted checks rerun against the
  current base. The strict required `validate` check
  from GitHub Actions integration ID `15368`, and the exact default-branch
  `.github/workflows/release-policy.yml` required workflow. Also require the
  exact `runtime-rights-eligibility` check, bound to the PR head SHA and emitted
  by an independently credentialed integration with no contents-write
  permission. It performs the private gate for every publisher purpose PR and
  every exact V1 execution-migration PR, with a bounded explicit not-applicable
  success only for other PRs; record and
  require its numeric integration ID during
  activation. A name-only
  status check is not sufficient for either trusted policy gate.
- `Restrict non-publisher branches`, targeting both `refs/heads/*` and
  `refs/heads/**/*`, excluding `~DEFAULT_BRANCH` and
  `refs/heads/publish/**/*` and
  `refs/heads/infrastructure/runtime-v1-execution/*`: restrict creation,
  update, and deletion. Only a separately recorded human maintainer team/role
  may bypass. Each runtime App must not be a bypass actor.
- `Restrict non-runtime tags`, targeting both `refs/tags/*` and
  `refs/tags/**/*`, excluding `refs/tags/runtime-v1-*` and
  `refs/tags/runtime-v1-*/*` and `refs/tags/runtime-v1-*/**/*`: restrict
  creation, update, and deletion. Only the separately recorded human
  maintainer team/role may bypass; GitHub App ID `4791815` must not be a bypass
  actor.
- `Restrict runtime publisher branches`, targeting `refs/heads/publish/**/*`:
  restrict creation, with only GitHub App ID `4791815` as an `always`
  integration bypass.
- `Protect runtime publisher branch updates`, targeting the same purpose
  branches, with no bypass actors: restrict every update, including
  fast-forward and non-fast-forward updates.
- `Protect runtime publisher branch deletion`, targeting the same purpose
  branches, with no bypass actors: block deletion.
- `Restrict runtime V1 execution branch creation`, targeting the exact
  one-level pattern `refs/heads/infrastructure/runtime-v1-execution/*`:
  restrict creation, with only the separately provisioned
  `NL Asset Runtime Execution Governance` GitHub App as an `always` integration
  bypass. Before activation, bind its App ID, node ID, installation ID, exact
  one-repository selection, and live-tested permissions into the private
  certification receipt. That App requires exactly Metadata read, Contents
  read and write, Pull requests read and write, Workflows read and write,
  Checks read, and Actions read; it has no Administration, Secrets,
  Environments, organization, R2, rights-policy, monitor, or routine-publisher
  credential. GitHub requires the
  Workflows repository permission to edit `.github/workflows/**`; do not add it
  to App ID `4791815`.
- `Protect runtime V1 execution branch updates`, targeting that exact same
  one-level pattern, with no bypass actors: restrict every update.
- `Protect runtime V1 execution branch deletion`, targeting that exact same
  one-level pattern, with no bypass actors: block deletion.
- `Restrict runtime release tag creation`, targeting
  `refs/tags/runtime-v1-*`, `refs/tags/runtime-v1-*/*`, and
  `refs/tags/runtime-v1-*/**/*`: restrict creation,
  with only GitHub App ID `4791815`
  (`NL Asset Runtime Publisher`) as an `always` integration bypass.
- `Protect immutable runtime release tags`, targeting the same tag pattern,
  including the nested runtime-prefixed-ref pattern, with no bypass actors:
  restrict updates and deletions. GitHub applies `File::FNM_PATHNAME`, so `*`
  does not cross `/`; all three include patterns are mandatory and must be tested
  against flat, one-level nested, and deeper nested runtime-prefixed refs before
  publication.

These eleven rulesets keep creation authority separate from immutable history.
The publisher App can create its one-commit purpose branches and one tag ref,
but cannot update/delete those refs or create an execution-migration ref. The
execution-governance App can create only the one-commit execution-migration ref
and is the gateway's exclusive merger for that exact PR after every required
workflow/check, review, receipt, current-base, and lease gate passes. It cannot
update/delete the purpose ref, create publisher refs/tags, merge any other PR
through the gateway, report rights eligibility, certify monitoring, or
administer rules. Neither App is a bypass actor for main, the general namespace,
or immutable-history rules.
Because GitHub rulesets cannot inspect candidate blob
content before a newly created public purpose ref becomes visible, the
publisher must validate the complete candidate commit and public boundary in a
clean isolated staging checkout before its first create-ref request. The
GitHub adapter must never receive raw masters, private metadata, or an
unvalidated tree. This is an additional activation gate, not a substitute for
the required workflow at merge time.

The activation certificate must enumerate all eleven ruleset IDs and exported
definitions and exercise an explicit provider ref matrix. At minimum it proves
that `runtime-v1-x`, `runtime-v1-x/y`, and `runtime-v1-x/y/z` enter both runtime
tag rules; that non-runtime flat and nested tags enter the non-runtime rule;
that the exact one-level execution branch enters only its isolated creation,
update, and deletion rules; and that malformed/deeper execution refs enter the
general non-publisher rule. Revoking or suspending either App installation must
deny a fresh create-ref request made with a newly minted token; a previously
minted installation token is also tested after revocation and its result is
recorded. A successful ruleset read alone is not a mutation-denial certificate.

Before activation, a live provider test must prove that a purpose PR whose base
becomes stale cannot merge, that bringing it up to date creates a newly
validated head presentation, and that `validate`, `release-policy`, and
`runtime-rights-eligibility` all rerun successfully against the actual current
base. Because purpose refs cannot be updated or deleted, an obsolete artifact
attempt is not rebased: the publisher recomputes the base- and byte-bound
artifact operation ID and creates a new one-commit ref. The obsolete unmerged
ref remains immutable evidence unless the owner invokes break glass.

An annotated tag object that fails pre-ref validation remains unreferenced and
does not consume the tag ref/name; its release ID remains permanently consumed
by the already merged immutable artifact directory. If an invalid named tag nevertheless appears
because of provider failure or credential compromise, freeze all publication
and revoke publisher access immediately. Break-glass recovery is never
automatic: preserve the ref, object, ruleset, and audit-log evidence; prove the
tag was never accepted or selected; obtain explicit owner authorization for the
destructive correction; temporarily exclude only that exact bad ref from the
immutable-tag ruleset; delete that exact ref; restore and independently verify
the ruleset; recertify the publisher; then create the correctly prevalidated
object/ref. Never move an existing tag, and never apply this runbook to a tag
that passed acceptance or became current.

“Accepted” is an exact durable terminal state, not merely a successful create
request or immediate API reread. A tag becomes accepted only after the reread
matches and a later successful reviewed-default-branch `schedule` audit,
started after tag creation, enumerates and validates that exact ref/object; the
private ledger then records a `runtime-tag-acceptance-v1` receipt binding the
numeric repository, tag ref/object, artifact commit, workflow/run ID, reviewed
default SHA, and completion time. No pointer branch may be created before that
receipt. After acceptance the tag is immutable even if later unselected. A
successfully reread tag awaiting its later scheduled audit is
`PENDING_ACCEPTANCE`, not
rejected: pointer work stays frozen and a later qualifying schedule may accept
it. Monitor delay, provider outage, or an absent qualifying run never authorizes
deletion. Only affirmative evidence that the created ref/object/receipt is
invalid moves it to terminal `REJECTED` and the owner-authorized exact-ref
break-glass procedure above. A purpose branch
is accepted only when its reviewed PR is merged and the private ledger records
the exact PR/head/merge receipt; any unmerged purpose ref remains unaccepted.

The same owner-authorized break-glass discipline applies if the App or provider
creates a publisher purpose branch that fails trusted validation and was never
merged. Freeze publication and revoke publisher access; preserve the ref, PR,
ruleset, and audit evidence; prove the branch was never merged or accepted;
obtain explicit owner authorization; temporarily exclude only that exact bad
ref from `Protect runtime publisher branch deletion` while the separate
no-update rule remains active; delete only that ref; restore and independently
verify the deletion rule; and recertify the publisher before retrying. Never rewrite a
purpose branch, never automate this recovery, and never apply it to accepted or
merged history. The no-update protection remains permanent.

An invalid, unmerged V1 execution-migration ref follows the same exact-ref
break-glass discipline. Freeze publication and revoke/suspend the execution
governance App; preserve the ref, PR, receipt, rulesets, checks, and audit-log
evidence; prove the branch was never merged and no execution closure accepted
it; obtain explicit owner authorization; temporarily exclude only that exact
ref from `Protect runtime V1 execution branch deletion` while its no-update rule
remains active; delete that one ref; restore and independently recertify all
eleven rulesets and both Apps before retrying with a new byte/base-bound
operation ID. Never update, reuse, automatically delete, or apply this procedure
to a merged execution migration.

Ordinary tombstones and immutable-release rules do not remediate secrets,
private classroom information, personal data, or legally prohibited metadata
already accepted into public Git history. Discovery of such material is an
incident stop: freeze publication and consumers, revoke/rotate affected
credentials, preserve a private forensic clone and provider audit evidence,
assess caches/forks/raw URLs, and obtain explicit owner plus legal/privacy
authorization before any destructive provider removal or history rewrite.
Coordinate cache invalidation and downstream consumer replacement; recreate the
public repository when a clean-history boundary is required. Afterwards
recertify repository/owner IDs, Apps, rulesets, workflows, commit-pinned URLs,
consumers, and recovery evidence before resuming. Never use this emergency
runbook to revise normal accepted creative or operational history.

The repository allows normal merge commits only; squash and rebase merging stay
disabled. Repository merge settings and the gateway's explicit safe merge
title/message are certified together. Before activation, live provider
certification may bind only fields the private gateway implementation actually
parses and verifies: the exact numeric provider principal, author, and
committer user IDs and node IDs; the permitted merge author and committer names
and email addresses; and the safe merge title/message for the publisher App's
merge API path. The gateway rejects any one of those exact implemented fields
when it differs from the private certificate before requesting another merge.
After merge, the private gateway/provider reconciliation rechecks those same
implemented fields as defense in depth. Provider-generated
signature or verification behavior is not certified and is not an acceptance
input under the current implementation. The public validator generic-scans the
complete raw commit bytes and proves graph/topology; it does not certify
provider identity, signature, or permission to accept a bad commit after it
becomes public.

For Windows validation and recovery, use a short checkout root and enable Git
long-path support where the host requires it. The public boundary permits only
ASCII tracked paths and caps each path component at 255 characters. That is a
per-component gate, not a fixed total-path guarantee; the effective total path
limit depends on the Windows, Git, and process configuration used for the
checkout.

`release-policy` is a read-only
`pull_request_target` gate loaded only from reviewed base `main`. It rejects
every fork head so V1 validation can never consume fork-controlled or stale tag
refs, then executes only trusted-base validators against the exact
same-repository candidate checkout.
Candidate workflow, validator, script, or dependency code is never executed.
Before dependency installation, the standard-library-only retained
public-boundary validator rejects nonregular modes, unknown paths, unsafe
history/metadata, and unexpected workflows. The retained wheelhouse verifier
then authenticates the exact requirements file and all eight wheel files. Pip
runs with `--no-index`, `--require-hashes`, and `--no-deps`. The trusted V1
pull-request lane next proves every immutable candidate schema path has the
exact reviewed-base bytes while evaluating the PR against reviewed-base schema
copies. Only after that proof may repository mode, through the trusted global
dispatcher, evaluate those candidate-tree schema copies. All four trusted tools
are loaded from the exact reviewed base and invoked with safe-path mode; the
dispatcher loads only its exact trusted sibling without adding candidate paths
to `sys.path`. Candidate legacy validators, generators,
tests, dispatchers, workflows, and dependencies are never imported or
executed. Mutable compatibility and discovery checks still run in the separate
unprivileged PR-head `validate` job. The trusted boundary inspects every new
commit tree and the
complete public commit metadata/message in `base..head`, so a private blob,
Git LFS pointer, credential-shaped identity, or hidden manifest mutation cannot
enter public merge history by being added and then deleted before the final
tree. Git LFS filters are forbidden because R2 is the sole runtime-byte
authority. Ordinary `validate` remains the independent PR-head build/test
check; it is useful evidence but cannot substitute for the exact required
workflow.

The tag-push run of `validate-runtime` is defense-in-depth only because GitHub
loads a push workflow from the tagged commit. It is not the trusted post-create
audit. The same workflow also runs hourly on reviewed default-branch code; that
path exhaustively enumerates every flat, nested, loose, or packed tag ref. It
uses the reviewed global dispatcher to reject every tag name outside the
currently recognized exact V1 release-ID grammar, then routes every V1
ref/object to the retained V1 authority. A manual dispatch is
deliberately absent because GitHub
would allow the selected ref to supply the workflow definition. The publisher
must also reread the created tag through the
GitHub API immediately, verify the exact object, tagger, message, target, and
object identity, and freeze before creating a pointer branch on any ambiguous
or differing response. A malformed tag can never pass pointer validation or
become current. Scheduled detection supplements those controls; it does not
replace pre-ref or immediate post-create proof. GitHub may disable scheduled
workflows in an inactive public repository, so publisher activation also
requires an external monitor credentialed with exactly Metadata read, Actions
read, and Contents read access, with no write scope, polling at least every 15
minutes. The monitor accepts only a successful
`schedule`-event run of the pinned workflow ID on the exact then-current
default-branch SHA, with complete flat and nested runtime-tag enumeration. Its
durable evidence binds the monitor's pinned numeric identity,
repository/workflow/run IDs, head SHA, event, conclusion, created/completed
times, exact workflow blob hash, runner label, and OCI image digest. A success
from a different workflow body or execution environment is not qualifying.
Publication freezes when the last qualifying completion is more than two
hours old, when the run or reviewed SHA is unreachable, or when the schedule is
disabled. Provider delay or outage does not extend that fixed window. Recovery
requires a new qualifying success on the current default SHA before publication
can resume; manually dispatched or tag-push runs do not satisfy liveness. The
exact monitor identity and live evidence must be recorded during activation.

The current global dispatcher is deliberately V1-only. V1 owns the
`runtime-v1-*` tag/release namespace, and every other tag name, including a
prospective `runtime-v2-*` name, is invalid today. The retained V1 validator
still enumerates and bounds the complete tag set, but semantically validates
only every `runtime-v1-`-prefixed ref; malformed or nested V1 refs fail. No V2
tag or artifact may be introduced until a separate owner-reviewed namespace
dispatcher migration adds and proves that disjoint route while preserving
retained V1 evidence. The three V1 schemas,
`tools/validate_runtime_release_v1.py`, the exact
hash-locked `requirements-ci.txt`, `tools/verify_v1_wheelhouse.py`, the exact
eight files under `ci/wheelhouse/`, and `.gitattributes` are immutable semantic
and bootstrap authority from the V1 activation marker, even before the first
accepted tag. A dependency or checkout-policy change requires a new versioned
contract and dependency lane; passing existing tags is not proof that a changed
schema engine has not expanded future V1 acceptance. Exactly the two workflows,
the compatibility dispatcher `tools/validate_runtime_release.py`, and the
public-boundary gate `tools/validate_public_boundary.py` form the evolvable V1
execution closure. They may change only through a
single-commit branch named
`infrastructure/runtime-v1-execution/<operation-id>` plus a reviewed private
`runtime-v1-execution-migration` authorization. The operation ID is SHA-256 of
`runtime-v1-execution-migration-v1`, the exact reviewed base, and each modified
allowed path/status/new-blob SHA-256 in path order, with LF after every field.
The commit must modify a nonempty subset of the exact four paths above; add,
delete, rename, manifest, or immutable-authority changes are rejected.
The trusted base boundary still enforces the read-only permissions, exact
bounded events, one-job shape, no actions, no services, no secrets, no mutable
dependency source, and immutable-bootstrap-first ordering. The dedicated receipt
may authorize only exact reviewed runner-label, timeout, and digest-pinned
container scalar changes inside workflow files. Every step name, order, command,
condition, environment mapping, offline installation flag, and trusted-tool
invocation remains byte-exact during this lane. Loss of the current runner or
OCI provider therefore has a repair lane without granting arbitrary workflow
execution authority; a required command-shape change needs a new-version or
separately designed owner-authorized incident contract. The private receipt
binds the old and new workflow/runner/container/tool closure, the exact base/head/ref and four
path blob set, both old/new adversarial and differential results, and the
external monitor's recertified workflow ID, workflow hash, runner, and image
digest before publication resumes.

The migration lane applies immediately after the activation marker, including
a proved zero-accepted-tag state. Its evidence inventories every V1 ref,
release directory, artifact PR/merge receipt, and current-pointer state. A
merged but not yet tagged first release remains an unaccepted artifact: both
old and new execution closures must validate its exact commit and repository,
and the receipt must prove that no tag or pointer selected it. When accepted
tags exist, every accepted V1 tag must pass both closures. The independently
credentialed policy service rejects any closure change without that dedicated
receipt; an ordinary rights approval is insufficient. The hourly global lane
invokes the reviewed dispatcher with Python safe-path mode. The dispatcher
exhaustively classifies every tag and loads the retained V1 validator only from
its exact reviewed sibling path; it never imports a candidate-controlled
module. Exact V1 pull-request semantics remain directly bound to the retained
validator, while pre-ref tag-object validation uses the global dispatcher
before delegating the exact V1 object proof.

The current Docker Hub digest gives content integrity, not durable provider
availability. Runtime publication cannot activate until the exact OCI image is
mirrored under NLL control with immutable identity and tested recovery evidence,
or the owner explicitly accepts provider-loss as an incident requiring the
execution-migration lane. The mirror does not loosen the digest pin, permit
online dependency resolution, or make the four-path migration lane optional.

A future-version migration must land its trusted global namespace dispatcher,
schema, validator, workflow, public-boundary rules, and disjoint manifest root
before the first V2 artifact PR or tag ref. That separately owner-reviewed
migration must define and test how every tag remains exhaustively classified,
how retained V1 evidence is presented to and validated by the locked V1
authority without asking its version-scoped audit to accept V2 names, and how
only the disjoint V2 lane reaches V2 authority. Until that migration is merged,
recertified, and enforced by the external policy integration, every V2 manifest
or tag change fails closed. This is a versioned change to global namespace
ownership, never a relaxation of V1. If a defect is discovered in locked V1
authority, freeze publication and use a separately reviewed new-version or
incident migration; never loosen or rewrite V1 merely to make historical audits
green.

## 7. Manifest contract

Existing legacy consumers discover compatibility data through the frozen root:

```text
manifests/index.json
```

That index points to:

- `assets.json`
- `collections.json`
- `themes.json`

Existing applications treat those generated root manifests as their legacy
public API.

The root manifests remain the frozen legacy entry point until a separately
reviewed consumer cutover. New released semantics use the commit-pinned catalog
path reached through `manifests/releases/current.json`; the selected catalog is
the V1 public API. Mutable branches and R2 are not semantic authority. While
that cutover is unresolved, all
`manifests/**` paths are frozen to ordinary branches. Only the two exact
publisher purpose lanes may change their expressly authorized release files.

## 8. Collections

Collections are reusable groups of stable asset IDs.

Examples might include:

- science props
- botanical linework
- museum ornaments
- ocean icons

Collections do not duplicate asset records. They reference IDs from the asset registry.

## 9. Themes

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

## 10. Failure behavior

Publishing should fail closed.

Do not partially publish an invalid asset set and then silently report success.

A future NL Asset Control exporter should:

1. validate candidate assets;
2. build derivatives into a staging location;
3. build manifests from staged output;
4. validate manifests and referenced files;
5. upload each exact content-addressed derivative to R2 and verify the remote
   object without overwriting an existing different object;
6. only then propose the reviewed immutable manifests to this Git repository.

R2 object publication does not select a release. A consumer-visible release
changes only through the separately reviewed current-pointer lane.

## 11. Private data prohibition

Generated output must never expose:

- private-library-root absolute paths;
- original ZIP names when not intentionally public;
- receipts;
- license keys;
- private license documents;
- internal review notes;
- private classroom/student information;
- credentials or secrets.

The runtime layer should know enough to serve an asset safely, not enough to reconstruct the private acquisition vault.
