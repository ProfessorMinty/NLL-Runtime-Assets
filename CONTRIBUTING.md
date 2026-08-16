# Contributing

`NLL-Runtime-Assets` is primarily a **generated runtime repository**.

## Preferred contribution path

Changes to published assets, runtime metadata, collections, and themes should normally originate in **NL Asset Control** and be regenerated into this repository.

Do not manually patch generated manifests to make a consumer work around bad source state. Fix the source state or exporter instead.

## Safe manual changes

Manual edits are appropriate for repository infrastructure such as:

- documentation;
- JSON schemas;
- validation tooling;
- CI workflows;
- publishing/integration contracts.

## Generated areas

The following paths are intended to become exporter-owned:

```text
assets/
manifests/
```

Once NL Asset Control owns those paths, treat direct edits there as exceptional recovery work only.

## Pull-request expectations

A change that affects the runtime contract should explain:

- what changed;
- whether the schema version changes;
- whether existing consumers remain compatible;
- whether stable asset IDs are affected;
- how the change was validated.

All manifest and derivative changes must pass the repository runtime validator.
