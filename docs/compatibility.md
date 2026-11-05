# Compatibility policy

Kionga components release independently, so at any moment a producer can be newer
or older than the component that reads its documents. Every contract in this
repository is either **open** or **closed** to unknown fields. The class decides
what a reader does with a field it does not know, and which schema changes are
compatible.

## Contract classes

| Class | Unknown field | Contracts | Why |
| --- | --- | --- | --- |
| Open: producer-to-gateway ingest | Accepted and ignored | `ingest/step-report.v1`, `ingest/log-batch.v1`, `ingest/trace.v1` | Runners, the agent runtime and the SDK upgrade on their own schedule. A newer producer that adds a fact must never lose the whole report against an older gateway. |
| Closed: user-authored documents | Rejected | `pipeline/v1`, `agent-graph/v2` | A misspelled field (`dependson`, `retires`) must fail validation instead of being silently ignored. |
| Closed: platform records | Rejected | `agent-graph/run-event.v1`, `agent-graph/artifact.v1` | One component writes them and the schema is their exact shape. `artifact.v1` is also hashed, so every byte is part of the record. |

Each schema states its class in its root `additionalProperties`: `true` for open,
`false` for closed. One published exception: `agent-graph/v2` accepts unknown
top-level fields, while its `nodes`, `edges` and `settings` are closed. It was
published that way, and closing the root would break stored drafts, so it stays. Open schemas also carry `"x-kionga-policy": "open"`. Nested
objects follow the class of their contract, except free-form maps such as
`context`, `metadata` and pipeline `parameters`, which are maps by design.

### Open contracts

- The reader accepts any property that the schema does not list and ignores it.
  It still type-checks the properties it knows: an open contract is not an
  untyped one.
- A producer may send a new optional field before every reader knows it. Add the
  field to the schema in the same release that starts sending it, so readers
  and tests can see it.
- A reader that later starts using a field must treat it as optional, because
  older producers do not send it.

Example: a runner adds `duration_ms` to its step reports. An older gateway
ignores it, and the step state still updates
(`ingest/examples/step-report/extra-field.json`).

### Closed contracts

- The reader rejects any property that the schema does not list.
- A new field is added to the schema, and released, before any writer emits it
  or any user is told to write it.

Example: `pipeline/v1` rejects `dependson` on a node and reports the property
name, so the author sees the typo.

## Compatible and breaking changes

A change is compatible when every document valid under the published schema stays
valid. Everything else is breaking.

| Compatible | Breaking |
| --- | --- |
| Add an optional property | Remove or rename a property |
| Allow more values: widen an `enum`, a `type`, a length or a numeric bound | Add a property to `required` |
| Loosen `additionalProperties` from `false` to `true` | Tighten `additionalProperties` from `true` or absent to `false` |
| Add `description`, `title`, examples or other annotations | Narrow an `enum` or a `type`, tighten a bound, or change a `pattern` |
| Add a new schema file | Delete or move a published schema file |

A breaking change is a new versioned file (for example
`ingest/step-report.v2.schema.json`) and a new major version of this repository.
The old file stays published and unchanged. Never mutate a published contract
incompatibly.

`tests/test_compatibility.py` enforces this table: it compares every schema with
its version at the latest release tag and fails on any breaking change, and it
checks that each schema declares its class.

## Gateway behavior

The class is a promise about the gateway. For open contracts the gateway decodes
request bodies without rejecting unknown fields; for closed ones it rejects them.
The platform pins this repository as a submodule; its handler tests must post
every `ingest/examples/*/extra-field.json` fixture to the real endpoint and
expect success, so a stricter decoder fails platform CI.
