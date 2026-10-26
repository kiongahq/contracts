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

## Router and join

`router` checks `route_1` to `route_4` in order (same grammar as conditions) and
sends the value out of the first matching port, or `default`. Only that branch
runs. `join` runs once every upstream node has finished or been skipped, and
outputs a JSON object keyed by upstream node ID. With `require: all` it fails if
any upstream branch was skipped or failed.

## Parallel execution

Nodes whose upstream nodes have all finished run concurrently, so independent
branches overlap in time. Event `seq` stays strictly increasing; events of
concurrent nodes interleave.

## Flows: map, bounded loop and subflow

These run a **published version** (`agv-…`, resource kind `agent_version`) as a
nested graph. The version ID pins the nested graph, so edits never change a
published parent. The runner receives every nested graph with the run; a
deployed artifact embeds them under `subflows`, each with its own
`content_sha256`, which the runtime verifies.

- `subflow` runs the version once with the inbound value as its input.
- `map` runs it once per item of a JSON list (or per non-empty line of text), at
  most `max_items` (20), with up to `concurrency` (4) in flight, and outputs the
  list of replies in item order.
- `loop` runs it, feeds each reply back as the next input, and stops when `until`
  matches the reply (`out`) or after `max_iterations` (10) (`exhausted`).

Nested runs share the parent's step, token and time budgets and its side-effect
approval. Nesting is limited to 3 levels and 10 distinct versions per run. A
nested failure fails the flow node, which can route to its `error` port.
`node.completed` for map and loop carries `iterations`.

## Human approval

`approval` renders `message`, creates a Kionga approval request
(`approval.requested` with `approval_id`) and waits. A project member with agents
write access approves or rejects it; the run's own credential cannot decide.
The value leaves through `approved` or `rejected` (`approval.resolved` with
`port`). A request not decided within `timeout_seconds` (10–290) leaves through
`rejected`.

## Streaming

`model` nodes using the platform chat model emit `node.delta` events with
incremental text. Deltas are best-effort (a consumer may miss some);
`node.completed` and `run.completed` always carry the full output.

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
