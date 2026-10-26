# Agent graph contract

The documents the native Agent Designer, the gateway and agent-runtime agree on.

| File | What it defines |
| --- | --- |
| `v2.schema.json` | The graph document a design stores and a version publishes. |
| `components.v1.json` | The component registry: node kinds, typed ports, configuration fields, side effects, timeouts and retries. |
| `run-event.v1.schema.json` | One event in a playground, evaluation or deployed run. |
| `artifact.v1.schema.json` | An immutable published version. |
| `templates/*.json` | Starter graphs shown under **Templates** in the designer. |
| `examples/v1-draft.json` | A draft as the version 1 designer saved it. It must stay valid. |
| `examples/hash-fixture.json` | The canonical behavior hash every implementation must reproduce. |

## Compatibility with version 1 drafts

Version 1 drafts have no `schema_version`, no edge ports and no settings. Readers
upgrade them in memory and never rewrite stored revisions:

1. A missing `schema_version` means 1; writers emit 2.
2. A missing `from_port` is the source component's first output (`out`, or `true` for
   a condition). A missing `to_port` is the target's first input (`in`).
3. Missing settings take the defaults in `v2.schema.json`.
4. An empty `model` on a model node means `llm`, the platform chat model.
5. A memory `strategy` other than `window` or `none` runs as `window` and is reported
   as a warning.
6. A version 1 condition holds free text. It still saves, but validation reports it as
   an error until it uses the operator grammar, so the draft cannot run or publish.

## Typed ports

Each edge joins an output port to an input port. The edge is valid when the output
type is one the input accepts, or a registered conversion turns it into one. A node
with several inbound edges receives every value; templates read them as `{context}`
or by node ID. Cycles are rejected; bounded loops are not part of version 2.

## Conditions

`expression` is `operator:argument` with an operator from
`condition_operators`, for example `contains:refund` or `longer_than:200`. Only the
selected branch runs; nodes reachable only through the other branch are reported as
`node.skipped`. A node with inbound edges runs when at least one of them carried a
value. A node with no inbound edges (the input, or a source such as a dataset loader)
always runs.

## Error ports

`model`, `tool`, `api`, `knowledge` and `storage` have a second output, `error`.
These nodes can fail with `node_error`, `resource_denied`, `resource_unavailable`
or a node `timeout`. When a node fails and its `error` port is connected, the run
emits `node.failed`, sends the redacted failure message (text) out of `error`, and
continues on that branch. Nodes fed only by the node's `out` port are skipped.
Unconnected error ports, side-effect refusals, budget failures, run timeouts and
cancellation still end the run.

## Extract

`extract` picks one field from a JSON value with a dot-separated `path` of object
keys and list indexes (`result.items.0.name`). Text input is parsed as JSON first.
When the field is missing, `missing: fail` fails the node and `missing: empty`
returns `null`.

## Side effects

`tool` and `api` nodes can change external systems. A playground or evaluation run
executes them only when the request sets `allow_side_effects: true`; otherwise the
node fails with `side_effects_not_approved` before any call is made. The gateway checks
the caller's project access on every resource call, so revoked access stops the next
call in a running graph.

## Canonical behavior hash

`content_sha256` identifies what a graph does, not how it is drawn. It is the SHA-256
of this UTF-8 JSON document:

```text
{"edges": [...], "nodes": [...], "schema_version": 2, "settings": {...}}
```

- `nodes`: `{"config", "id", "kind"}` for every node, sorted by `id`. `config` drops
  keys whose value is the empty string. Names, positions and groups are excluded.
- `edges`: `{"from", "to"}` plus `from_port` and `to_port` when non-empty, sorted by
  `(from, from_port, to, to_port)`.
- `settings`: as stored (integers only).
- Serialization: object keys sorted, no whitespace, non-ASCII characters written as
  UTF-8, HTML characters not escaped, and U+2028/U+2029 written as ` `/` `.

Python reference: `json.dumps(doc, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` followed by the U+2028/U+2029 replacement. Go: encode a map with
`SetEscapeHTML(false)` and trim the trailing newline.
