# Runtime validation and discovery authority

The public repository stores runtime manifests and generated discovery JSON, but deliberately excludes derivative binaries. Validation therefore has two distinct gates.

## Public semantic gate

GitHub Actions runs only checks that a clean checkout can prove without Cloudflare credentials or ignored binary payloads:

```text
python tools/validate_identity_contracts.py
python tools/validate_runtime_semantics.py
python tools/generate_discovery.py --check
python tools/validate_discovery.py
python -m unittest discover -s tests -v
```

The gate validates schemas, stable IDs, manifest references, deterministic ordering, discovery exact-set equality, preferred derivative URL/hash/version consistency, eight-slot theme shape, and the absence of private/internal asset fields. It never treats missing Git-ignored binaries as a public-repository defect.

`manifests/assets.json` is the authoritative public root for discovery. Only records marked both `READY` and `ELIGIBLE` enter discovery. `tools/generate_discovery.py` is the sole discovery generator. Its `--check` mode builds into an isolated temporary directory and byte-compares the complete generated tree, including stale or missing shards.

Theme manifests are suggestion recipes, not proof of a completed production theme pack. Discovery records every required slot and marks a recipe `COMPLETE` only when all eight filtered slots contain an eligible asset; otherwise it records `INCOMPLETE` and the exact `missingSlots`.

## Private byte-integrity gate

The publisher environment, where approved derivatives are present, runs:

```text
python tools/validate_runtime.py
```

That command includes all public semantic checks and additionally verifies every derivative's existence, byte count, and SHA-256. Later publisher phases also verify candidate/release receipts and Cloudflare R2 state. The private gate is not run in public CI and requires no change to the repository's binary exclusion.
